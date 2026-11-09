"""Запуск сводки.

    python -m svodka                    # живые источники, страница svodka.html
    python -m svodka --offline          # сохранённые ответы из examples/fixtures, без интернета
    python -m svodka --offline -o examples/svodka-primer.html
"""

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from . import istochniki
from .nastroyki import Nastroyki
from .stranica import stranica

KOREN = Path(__file__).resolve().parent.parent
FIKSTURY = KOREN / "examples" / "fixtures"


class FiksturnyZapros:
    """Подменяет HTTP: URL сопоставляется с файлом по regex из karta.json. Нет совпадения, значит нет сети."""

    def __init__(self, papka=FIKSTURY):
        self.papka = Path(papka)
        opis = json.loads((self.papka / "karta.json").read_text(encoding="utf-8"))
        self.segodnya = dt.date.fromisoformat(opis["segodnya"])
        self.karta = [(re.compile(rx), fayl) for rx, fayl in opis["karta"]]

    def __call__(self, url, kodirovka="utf-8", tajmaut=20):
        for rx, fayl in self.karta:
            if rx.search(url):
                return (self.papka / fayl).read_text(encoding="utf-8")
        raise OSError(f"нет сохранённого ответа для {url}")


def sobrat(zapros, segodnya, kesh, nastr=Nastroyki(), sobrano=None):
    """Собирает все источники и возвращает (html, новые_цены_или_None, oshibki)."""
    oshibki = []
    cb = istochniki.sobrat_cb(zapros, segodnya, oshibki)
    novosti = istochniki.sobrat_novosti(zapros, segodnya, oshibki)
    ceny, obnovleno = istochniki.sobrat_ceny(zapros, kesh, segodnya, oshibki)
    pogoda = istochniki.sobrat_pogodu(zapros, nastr.rajony, oshibki)
    sobrano = sobrano or dt.datetime.now()
    stranitsa = stranica(cb, novosti, ceny, pogoda, oshibki, segodnya, sobrano, nastr)
    return stranitsa, (ceny if obnovleno else None), oshibki, novosti


def main(argv=None):
    ap = argparse.ArgumentParser(prog="svodka", description="Утренняя сводка закупщика зерна")
    ap.add_argument("--offline", action="store_true", help="собрать из examples/fixtures без интернета")
    ap.add_argument("-o", "--vyhod", default="svodka.html", help="куда записать страницу")
    ap.add_argument("--kesh", default="ceny.json", help="последние проверенные цены (обновляется сам)")
    a = ap.parse_args(argv)

    if a.offline:
        zapros = FiksturnyZapros()
        segodnya = zapros.segodnya
        kesh = json.loads((FIKSTURY / "ceny-kesh.json").read_text(encoding="utf-8"))
        sobrano = dt.datetime.combine(segodnya, dt.time(7, 30))
    else:
        zapros, segodnya, sobrano = istochniki.zapros_http, dt.date.today(), None
        put = Path(a.kesh)
        istok = put if put.exists() else FIKSTURY / "ceny-kesh.json"
        kesh = json.loads(istok.read_text(encoding="utf-8"))

    stranitsa, novye, oshibki, novosti = sobrat(zapros, segodnya, kesh, sobrano=sobrano)
    if novye and not a.offline:
        Path(a.kesh).write_text(json.dumps(novye, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(a.vyhod).write_text(stranitsa, encoding="utf-8")
    glavnyh = len([n for n in novosti if n["ball"] >= 3][:5])
    print(f"Готово: {a.vyhod}  новостей {len(novosti)}, главных {glavnyh}, замечаний {len(oshibki)}")
    for o in oshibki:
        print(" -", o)
    return 0
