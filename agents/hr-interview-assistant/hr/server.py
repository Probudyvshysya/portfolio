"""Сервер HR-помощника: одна страница в браузере + API. Слушает только 127.0.0.1 — снаружи не виден.

Запуск: .venv\\Scripts\\python -m hr.server   (или ZAPUSK.cmd)
"""

import json
import os
import shutil
import subprocess
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import chistka, otkliki, plan, profil, znaniya
from . import hranilishche as H
from .ochered import Ochered
from .zapis import Zapis, vyrovnyat_i_smeshat

STATIC = Path(__file__).parent / "static"
PORT = 8790
RASSHIRENIYA = {".wav", ".mp3", ".m4a", ".ogg", ".opus", ".webm", ".mp4", ".mkv", ".mov", ".aac", ".flac", ".wma"}


def ollama_otvechaet():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2)
        return True
    except Exception:
        return False


def v_wav(src, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)], check=True)


def sozdat_app(ochered=None, zapis=None, zapuskat=True, hosty=("127.0.0.1", "localhost")):
    zapis = zapis or Zapis()
    ochered = ochered or Ochered(zapis_idet=zapis.idet)

    @asynccontextmanager
    async def lifespan(app):
        if zapuskat:
            ochered.zapustit()
        yield
        ochered.ostanovit()

    app = FastAPI(title="HR-помощник", lifespan=lifespan)
    # Чужой сайт в браузере HR не должен достучаться до данных кандидатов:
    # Host — защита от подмены адреса (DNS rebinding), Origin — от подделанных запросов (CSRF)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosty))
    svoi = {f"http://{h}:{PORT}" for h in hosty} | {f"http://{h}" for h in hosty}

    @app.middleware("http")
    async def tolko_svoya_stranica(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            chuzhoy_origin = origin is not None and origin not in svoi
            if chuzhoy_origin or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "запрос не с этой страницы"}, status_code=403)
        return await call_next(request)

    def k_ili_404(i):
        try:
            m = H.kandidat(i)
        except ValueError:
            m = None
        if not m:
            raise HTTPException(404, "кандидат не найден")
        return m

    def v_ili_404(i):
        try:
            v = H.vakansiya(i)
        except ValueError:
            v = None
        if not v:
            raise HTTPException(404, "вакансия не найдена")
        return v

    @app.get("/", response_class=HTMLResponse)
    def glavnaya():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/sostoyanie")
    def sostoyanie():
        zhdut = [k["id"] for k in H.spisok_kandidatov() if k["status"] == H.OCHERED]
        return {"prilozhenie": "hr-pomoshchnik", "ollama": ollama_otvechaet(), "razbiraetsya": ochered.tekushchiy, "v_ocheredi": len(zhdut),
                "zapis": zapis.sostoyanie()}

    # ---------- вакансии ----------
    @app.get("/api/chek-list")
    def chek_list():
        return [{"id": k, "vopros": v} for k, v in profil.CHEK_LIST]

    @app.get("/api/vakansii")
    def vakansii():
        return H.spisok_vakansiy()

    @app.get("/api/vakansii/{i}")
    def vakansiya(i: str):
        return v_ili_404(i)

    @app.post("/api/vakansii/sobrat-profil")
    def sobrat_profil(d: dict = Body(...)):
        if not ollama_otvechaet():
            raise HTTPException(503, "Модель не запущена. Откройте ZAPUSK.cmd")
        return {"profil": profil.sobrat(d.get("nazvanie", ""), d.get("faktura", ""), d.get("otvety", {}))}

    @app.post("/api/vakansii/{i}/plan")
    def sobrat_plan(i: str):
        v = v_ili_404(i)
        if not ollama_otvechaet():
            raise HTTPException(503, "Модель не запущена. Откройте ZAPUSK.cmd")
        try:
            p = plan.sostavit(v["profil"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        H.zhurnal(f"собран план собеседования для вакансии {i}")
        return H.sohranit_plan(i, p, v["profil"])

    @app.post("/api/vakansii")
    def sohranit_vakansiyu(d: dict = Body(...)):
        if not d.get("nazvanie", "").strip() or not d.get("profil", "").strip():
            raise HTTPException(400, "нужны название и профиль")
        if d.get("id"):
            v_ili_404(d["id"])
        return H.sohranit_vakansiyu(d["nazvanie"].strip(), d["profil"], d.get("faktura", ""), d.get("otvety"), d.get("id"))

    # ---------- кандидаты ----------
    @app.get("/api/kandidaty")
    def kandidaty():
        vak = {v["id"]: v["nazvanie"] for v in H.spisok_vakansiy()}
        return [{**k, "vakansiya": vak.get(k["vakansiya_id"], "—")} for k in H.spisok_kandidatov()]

    @app.get("/api/kandidaty/{i}")
    def kandidat(i: str):
        m = k_ili_404(i)
        p = H.papka(i)
        otchet = json.loads((p / "otchet.json").read_text(encoding="utf-8")) if (p / "otchet.json").exists() else None
        reps = json.loads((p / "rasshifrovka.json").read_text(encoding="utf-8")) if (p / "rasshifrovka.json").exists() else []
        return {"meta": m, "otchet": otchet, "repliki": reps, "est_zapis": (p / "proslushka.wav").exists()}

    def proverit_novogo(imya, vakansiya_id, soglasie):
        if not soglasie:
            raise HTTPException(400, "без согласия кандидата на запись разбирать нельзя (ст. 9 152-ФЗ)")
        if not imya.strip():
            raise HTTPException(400, "укажите имя кандидата")
        v_ili_404(vakansiya_id)

    @app.post("/api/kandidaty")
    def zagruzit(imya: str = Form(...), vakansiya_id: str = Form(...), soglasie: bool = Form(False),
                 odna: UploadFile | None = File(None), hr: UploadFile | None = File(None),
                 kandidat: UploadFile | None = File(None)):
        proverit_novogo(imya, vakansiya_id, soglasie)
        if not (odna or (hr and kandidat)):
            raise HTTPException(400, "нужна одна запись или две дорожки (HR и кандидат)")
        faily = {"odna": odna} if odna else {"hr": hr, "kandidat": kandidat}
        for f in faily.values():
            if Path(f.filename or "").suffix.lower() not in RASSHIRENIYA:
                raise HTTPException(400, f"не знаю такой формат: {f.filename}")
        m = H.novyy_kandidat(imya.strip(), vakansiya_id, status=H.ZAPIS)
        p = H.papka(m["id"])
        try:
            for klyuch, f in faily.items():
                isx = p / f"isxodnik-{klyuch}{Path(f.filename).suffix.lower()}"
                with open(isx, "wb") as out:
                    shutil.copyfileobj(f.file, out)
                v_wav(isx, p / f"{klyuch}.wav")
                isx.unlink()
            if odna:
                shutil.copy(p / "odna.wav", p / "proslushka.wav")
                imena = {"odna": "odna.wav"}
            else:
                vyrovnyat_i_smeshat(p)
                imena = {"hr": "hr.wav", "kandidat": "kandidat.wav"}
        except subprocess.CalledProcessError:
            shutil.rmtree(p, ignore_errors=True)
            raise HTTPException(400, "Файл не читается. Это точно аудио или видео?")
        H.zhurnal(f"загружено собеседование {m['id']}")
        return H.obnovit_kandidata(m["id"], status=H.OCHERED, faily=imena)

    @app.post("/api/zapis/nachat")
    def zapis_nachat(d: dict = Body(...)):
        proverit_novogo(d.get("imya", ""), d.get("vakansiya_id", ""), d.get("soglasie"))
        if zapis.idet():
            raise HTTPException(409, "запись уже идёт")
        m = H.novyy_kandidat(d["imya"].strip(), d["vakansiya_id"], status=H.ZAPIS)
        try:
            ustr = zapis.nachat(m["id"], H.papka(m["id"]))
        except Exception as e:
            shutil.rmtree(H.papka(m["id"]), ignore_errors=True)
            raise HTTPException(500, f"не удалось начать запись: {e}")
        H.zhurnal(f"начата запись {m['id']}")
        return {"kandidat": m, "ustroystva": ustr}

    @app.post("/api/zapis/stop")
    def zapis_stop():
        if not zapis.idet():
            raise HTTPException(409, "запись не идёт")
        i, dlit = zapis.ostanovit()
        H.zhurnal(f"запись остановлена {i}, {dlit} с")
        return H.obnovit_kandidata(i, status=H.OCHERED, faily={"hr": "hr.wav", "kandidat": "kandidat.wav"},
                                   dlitelnost_s=dlit)

    @app.get("/api/kandidaty/{i}/zapis")
    def proslushka(i: str):
        k_ili_404(i)
        f = H.papka(i) / "proslushka.wav"
        if not f.exists():
            raise HTTPException(404, "записи нет")
        return FileResponse(f, media_type="audio/wav")

    @app.post("/api/kandidaty/{i}/reshenie")
    def reshenie(i: str, d: dict = Body(...)):
        k_ili_404(i)
        r = d.get("reshenie")
        if r not in ("дальше", "отказ", None):
            raise HTTPException(400, "решение: дальше / отказ")
        H.zhurnal(f"решение по {i}: {r}")
        return H.obnovit_kandidata(i, reshenie=r, reshenie_data=H.seychas() if r else None)

    @app.post("/api/kandidaty/{i}/peresobrat")
    def peresobrat(i: str):
        m = k_ili_404(i)
        if m["status"] in (H.ZAPIS, H.RASSHIFROVKA, H.ZAKLYUCHENIE):
            raise HTTPException(409, "разбор ещё идёт")
        if not m.get("faily") and not (H.papka(i) / "rasshifrovka.txt").exists():
            raise HTTPException(409, "Нечего разбирать: нет ни записи, ни расшифровки")
        (H.papka(i) / "otchet.json").unlink(missing_ok=True)
        return H.obnovit_kandidata(i, status=H.OCHERED, oshibka=None)

    @app.post("/api/kandidaty/{i}/popravka")
    def popravka(i: str, d: dict = Body(...)):
        m = k_ili_404(i)
        text = (d.get("text") or "").strip()
        if len(text) < 5:
            raise HTTPException(400, "напишите поправку словами")
        r = H.dobavit_pravilo(text, m["vakansiya_id"] if d.get("dlya") == "eta" else None, i)
        return r

    @app.delete("/api/kandidaty/{i}")
    def udalit(i: str):
        m = k_ili_404(i)
        if (zapis.idet() and zapis.kandidat_id == i) or ochered.tekushchiy == i:
            raise HTTPException(409, "сейчас идёт запись или разбор")
        shutil.rmtree(H.papka(i), ignore_errors=True)
        H.zhurnal(f"удалён вручную кандидат {m['id']}")
        return {"ok": True}

    # ---------- отклики (этап 2) ----------
    def o_ili_404(i):
        try:
            x = otkliki.otklik(i)
        except ValueError:
            x = None
        if not x:
            raise HTTPException(404, "отклик не найден")
        return x

    @app.get("/api/otkliki")
    def otkliki_spisok(vakansiya_id: str | None = None):
        return otkliki.spisok(vakansiya_id)

    @app.post("/api/otkliki")
    def otklik_novyy(d: dict = Body(...)):
        v_ili_404(d.get("vakansiya_id", ""))
        if not (d.get("imya") or "").strip() or len((d.get("rezyume") or "").strip()) < 50:
            raise HTTPException(400, "Нужны имя и текст резюме")
        return otkliki.novyy(d["imya"].strip(), d["vakansiya_id"], d["rezyume"].strip(), istochnik="вручную")

    @app.post("/api/otkliki/{i}/razobrat")
    def otklik_razobrat(i: str):
        x = o_ili_404(i)
        v = v_ili_404(x["vakansiya_id"])
        if not ollama_otvechaet():
            raise HTTPException(503, "Модель не запущена. Откройте ZAPUSK.cmd")
        x = otkliki.obnovit(i, razbor=otkliki.razobrat(x["rezyume"], v["profil"]))
        return otkliki.obnovit(i, pismo=otkliki.podgotovit_pismo(x, v))

    @app.post("/api/otkliki/{i}/reshenie")
    def otklik_reshenie(i: str, d: dict = Body(...)):
        """HR решает сама: звать или отказать. Письмо готовится под её решение и ждёт её же «Отправить»."""
        x = o_ili_404(i)
        v = v_ili_404(x["vakansiya_id"])
        r = d.get("reshenie")
        if r not in ("звать", "отказ", None):
            raise HTTPException(400, "решение: звать / отказ")
        tip = {"звать": "приглашение", "отказ": "отказ"}.get(r)
        pismo = {"tip": tip, "text": otkliki.tekst_pisma(tip, x, v), "status": "ждёт HR", "kto": None, "kogda": None} if tip else None
        H.zhurnal(f"решение по отклику {i}: {r}")
        return otkliki.obnovit(i, reshenie=r, pismo=pismo)

    @app.post("/api/otkliki/{i}/pismo")
    def otklik_pismo(i: str, d: dict = Body(...)):
        x = o_ili_404(i)
        if not x.get("pismo"):
            raise HTTPException(409, "письма нет")
        p = {**x["pismo"], "text": (d.get("text") or x["pismo"]["text"]).strip()}
        if d.get("otpravit"):
            # hh подключим, когда дадут доступ; пока отмечаем, что HR одобрила, и пишем в журнал
            p.update(status="отправлено", kto="HR", kogda=H.seychas())
            H.zhurnal(f"письмо по отклику {i} одобрено HR ({p['tip']})")
        return otkliki.obnovit(i, pismo=p)

    @app.delete("/api/otkliki/{i}")
    def otklik_udalit(i: str):
        o_ili_404(i)
        otkliki.udalit(i)
        H.zhurnal(f"удалён отклик {i}")
        return {"ok": True}

    @app.post("/api/vakansii/{i}/nastroyki")
    def vak_nastroyki(i: str, d: dict = Body(...)):
        v = v_ili_404(i)
        sama, podpis = bool(d.get("pisma_sama")), (d.get("podpis") or "").strip()
        if sama and not podpis:
            raise HTTPException(400, "Чтобы помощник отправлял приглашения сам, укажите подпись")
        return H.sohranit_vakansiyu(v["nazvanie"], v["profil"], v.get("faktura", ""), v.get("otvety"), i,
                                    pisma_sama=sama, podpis=podpis)

    # ---------- база знаний ----------
    @app.get("/api/znaniya")
    def znaniya_spisok():
        out = []
        for f in znaniya.dokumenty():
            kuski = znaniya._kuski(f)
            out.append({"fayl": f.name, "dokument": kuski[0]["dokument"] if kuski else f.stem,
                        "razdely": [k["razdel"] for k in kuski if k["razdel"]], "kuskov": len(kuski)})
        return out

    @app.post("/api/znaniya")
    def znaniya_dobavit(fayl: UploadFile = File(...)):
        imya = Path(fayl.filename or "").name
        if Path(imya).suffix.lower() not in (".md", ".txt") or not imya:
            raise HTTPException(400, "Пока принимаю .md и .txt, PDF и Word появятся в следующей версии")
        dannye = fayl.file.read()
        try:
            dannye.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(400, "файл не в кодировке UTF-8")
        (znaniya.PAPKA / imya).write_bytes(dannye)
        H.zhurnal(f"в базу знаний добавлен документ {imya}")
        return {"ok": True, "fayl": imya}

    @app.get("/api/znaniya/iskat")
    def znaniya_iskat(q: str):
        return znaniya.iskat(q, 3)

    # ---------- безопасность ----------
    @app.get("/api/bezopasnost")
    def bezopasnost():
        ks = H.spisok_kandidatov()
        return {"papka_dannyh": str(H.ROOT), "adres": f"http://127.0.0.1:{PORT} (только этот компьютер)",
                "kandidatov": len(ks), "otkazov_k_udaleniyu": sum(1 for k in ks if k.get("reshenie") == "отказ"),
                "srok_dney": chistka.SROK_DNEY, "internet_proverka": os.environ.get("HR_INTERNET", "1") == "1",
                "vyhod": H.chitat_zhurnal_vyhoda()}

    # ---------- правила ----------
    @app.get("/api/pravila")
    def pravila():
        vak = {v["id"]: v["nazvanie"] for v in H.spisok_vakansiy()}
        return [{**r, "vakansiya": vak.get(r["vakansiya_id"]) if r["vakansiya_id"] else "все вакансии"}
                for r in H.pravila()]

    @app.put("/api/pravila/{i}")
    def izmenit(i: str, d: dict = Body(...)):
        H.izmenit_pravilo(i, d.get("text", ""))
        return {"ok": True}

    @app.delete("/api/pravila/{i}")
    def udalit_pravilo(i: str):
        H.udalit_pravilo(i)
        return {"ok": True}

    return app



def main():
    import uvicorn

    uvicorn.run(sozdat_app(), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
