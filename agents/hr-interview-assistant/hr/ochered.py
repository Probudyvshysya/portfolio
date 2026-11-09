"""Очередь разбора: один фоновый поток, кандидаты по одному в порядке поступления.

Статус хранится в meta.json, поэтому после перезапуска незаконченное продолжается само.
Пока идёт запись созвона, очередь ждёт: тяжёлый разбор не должен тормозить звонок.
"""

import json
import threading
import time
import traceback
from pathlib import Path

from . import chistka
from . import hranilishche as H

ROOT_KOMPLEKT = Path(__file__).resolve().parent.parent


def nastoyashchiy_rasshifrovshchik():
    import sys

    sys.path.insert(0, str(ROOT_KOMPLEKT))
    import rasshifrovka_po_rolyam as R

    kesh = {}

    def run(m, papka):
        if "run" not in kesh:
            import torch

            torch.set_num_threads(R.POTOKI)
            kesh["run"] = R.gigaam_engine("v3_e2e_rnnt")
        f = m["faily"]
        reps = R.rasshifrovat(hr=papka / f["hr"] if "hr" in f else None,
                              kandidat=papka / f["kandidat"] if "kandidat" in f else None,
                              odna=papka / f["odna"] if "odna" in f else None, run=kesh["run"])
        return reps, R.v_tekst(reps)

    return run


def nastoyashchiy_otchetchik():
    import sys

    sys.path.insert(0, str(ROOT_KOMPLEKT))
    import otchet

    import os
    import time

    from . import proverka

    def run(profil, tekst, pravila, imya=""):
        o, zamer = otchet.sostavit(profil, tekst, pravila)
        t0 = time.perf_counter()
        try:
            o["proverka_faktov"] = proverka.proverit(tekst, imya, internet=os.environ.get("HR_INTERNET", "1") == "1")
        except Exception as e:  # проверка — дополнение: её сбой не должен ломать заключение
            o["proverka_faktov"], o["proverka_oshibka"] = [], f"{type(e).__name__}: {e}"
        zamer["vremya_proverki_s"] = round(time.perf_counter() - t0, 1)
        o = otchet.dovesti(o, profil, tekst)  # после проверки фактов: ошибки в нормах влияют на оценки и совет
        return o, zamer, otchet.v_markdown

    return run


class Ochered:
    def __init__(self, rasshifrovshchik=None, otchetchik=None, zapis_idet=lambda: False):
        self._rasshifrovshchik = rasshifrovshchik
        self._otchetchik = otchetchik
        self.zapis_idet = zapis_idet
        self.tekushchiy = None
        self._stop = threading.Event()
        self._posledn_chistka = 0.0

    @property
    def rasshifrovshchik(self):
        if self._rasshifrovshchik is None:
            self._rasshifrovshchik = nastoyashchiy_rasshifrovshchik()
        return self._rasshifrovshchik

    @property
    def otchetchik(self):
        if self._otchetchik is None:
            self._otchetchik = nastoyashchiy_otchetchik()
        return self._otchetchik

    def vosstanovit(self):
        """Разбор, прерванный перезапуском, — снова в очередь."""
        for k in H.spisok_kandidatov():
            if k["status"] in (H.RASSHIFROVKA, H.ZAKLYUCHENIE):
                H.obnovit_kandidata(k["id"], status=H.OCHERED)
            elif k["status"] == H.ZAPIS:  # программа закрылась посреди записи: разбираем, что успело записаться
                self.spasti_zapis(k["id"])

    def spasti_zapis(self, i):
        from .zapis import vyrovnyat_i_smeshat

        p = H.papka(i)
        try:
            vyrovnyat_i_smeshat(p)
            H.obnovit_kandidata(i, status=H.OCHERED, faily={"hr": "hr.wav", "kandidat": "kandidat.wav"},
                                primechanie="запись была прервана — разобрано то, что успело записаться")
        except Exception as e:
            H.obnovit_kandidata(i, status=H.OSHIBKA, oshibka=f"запись прервана и не читается: {e}")

    def sleduyushchiy(self):
        zhdut = [k for k in H.spisok_kandidatov() if k["status"] == H.OCHERED]
        return min(zhdut, key=lambda k: (k["sozdan"], k.get("poryadok", 0))) if zhdut else None

    def razobrat(self, i):
        m = H.kandidat(i)
        papka = H.papka(i)
        self.tekushchiy = i
        try:
            if not (papka / "rasshifrovka.txt").exists():
                H.obnovit_kandidata(i, status=H.RASSHIFROVKA, oshibka=None)
                t0 = time.perf_counter()
                reps, tekst = self.rasshifrovshchik(m, papka)
                (papka / "rasshifrovka.json").write_text(json.dumps(reps, ensure_ascii=False, indent=1), encoding="utf-8")
                (papka / "rasshifrovka.txt").write_text(tekst, encoding="utf-8")
                H.obnovit_kandidata(i, vremya_rasshifrovki_s=round(time.perf_counter() - t0, 1))
            H.obnovit_kandidata(i, status=H.ZAKLYUCHENIE, oshibka=None)
            v = H.vakansiya(m["vakansiya_id"])
            if v is None:
                raise RuntimeError("вакансия удалена — нечем сравнивать")
            sp, pravila_tekst = H.pravila_dlya(m["vakansiya_id"])
            tekst = (papka / "rasshifrovka.txt").read_text(encoding="utf-8")
            o, zamer, v_markdown = self.otchetchik(v["profil"], tekst, pravila_tekst, m["imya"])
            zamer["pravil_uchteno"] = len(sp)
            (papka / "otchet.json").write_text(json.dumps({"zamer": zamer, "otchet": o}, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
            (papka / "otchet.md").write_text(v_markdown(o, m["imya"]), encoding="utf-8")
            H.obnovit_kandidata(i, status=H.GOTOVO, gotovo=H.seychas(), vremya_zaklyucheniya_s=zamer.get("vremya_s"),
                                sovet=o.get("sovet"),
                                pravil_uchteno=len(sp))
            H.zhurnal(f"разобран кандидат {i}")
        except Exception as e:  # ошибку показываем HR, очередь не падает
            H.obnovit_kandidata(i, status=H.OSHIBKA, oshibka=f"{type(e).__name__}: {e}")
            H.zhurnal(f"ошибка разбора {i}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            self.tekushchiy = None

    def shag(self):
        """Один шаг цикла: чистка раз в час + следующий кандидат. Возвращает id разобранного или None."""
        if time.time() - self._posledn_chistka > 3600:
            chistka.pochistit()
            self._posledn_chistka = time.time()
        if self.zapis_idet():
            return None
        k = self.sleduyushchiy()
        if k:
            self.razobrat(k["id"])
            return k["id"]
        return None

    def zapustit(self):
        self.vosstanovit()

        def cikl():
            while not self._stop.is_set():
                if self.shag() is None:
                    self._stop.wait(2)

        threading.Thread(target=cikl, daemon=True, name="ochered").start()

    def ostanovit(self):
        self._stop.set()
