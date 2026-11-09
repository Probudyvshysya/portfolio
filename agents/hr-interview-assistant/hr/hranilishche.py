"""Хранение — папки и JSON, без базы данных: сисадмин видит всё глазами, резервная копия = копия папки.

dannye/
  vakansii/<id>.json
  kandidaty/<id>/meta.json, записи, rasshifrovka.*, otchet.*
  pravila.json
  zhurnal.log
"""

import json
import os
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("HR_DANNYE", Path(__file__).resolve().parent.parent / "dannye"))
LOCK = threading.RLock()
ID_RE = re.compile(r"^[a-z0-9-]{6,40}$")

# статусы кандидата
ZAPIS, OCHERED, RASSHIFROVKA, ZAKLYUCHENIE, GOTOVO, OSHIBKA = (
    "запись", "в очереди", "расшифровка", "заключение", "готово", "ошибка")


def seychas():
    return datetime.now().isoformat(timespec="seconds")


def novyy_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


def proverit_id(i):
    if not ID_RE.match(i or ""):
        raise ValueError(f"плохой id: {i!r}")
    return i


def _zapisat(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _chitat(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def zhurnal(text):
    with LOCK:
        ROOT.mkdir(parents=True, exist_ok=True)
        with open(ROOT / "zhurnal.log", "a", encoding="utf-8") as f:
            f.write(f"{seychas()} {text}\n")


def zhurnal_vyhoda(text):
    """Всё, что программа отправила в интернет, — для проверки службой безопасности."""
    with LOCK:
        ROOT.mkdir(parents=True, exist_ok=True)
        with open(ROOT / "vyhod.log", "a", encoding="utf-8") as f:
            f.write(f"{seychas()} {text}\n")


def chitat_zhurnal_vyhoda(n=200):
    try:
        return (ROOT / "vyhod.log").read_text(encoding="utf-8").splitlines()[-n:][::-1]
    except FileNotFoundError:
        return []


# ---------- вакансии ----------

def vakansiya(i):
    return _chitat(ROOT / "vakansii" / f"{proverit_id(i)}.json")


def spisok_vakansiy():
    papka = ROOT / "vakansii"
    out = [_chitat(p) for p in sorted(papka.glob("*.json"))] if papka.exists() else []
    return sorted(out, key=lambda v: v["sozdana"], reverse=True)


def sohranit_vakansiyu(nazvanie, profil, faktura="", otvety=None, i=None, **dop):
    with LOCK:
        old = vakansiya(i) if i else None
        v = {**(old or {"id": novyy_id(), "sozdana": seychas()}),
             "nazvanie": nazvanie, "profil": profil, "faktura": faktura, "otvety": otvety or {}, "izmenena": seychas(), **dop}
        _zapisat(ROOT / "vakansii" / f"{v['id']}.json", v)
        return v


def sohranit_plan(i, plan, profil):
    """План собеседования хранится в вакансии вместе с профилем, по которому собран: профиль поменяли — план устарел."""
    with LOCK:
        v = vakansiya(i)
        if v is None:
            raise KeyError(i)
        v["plan"] = {**plan, "sobran": seychas(), "po_profilyu": profil}
        _zapisat(ROOT / "vakansii" / f"{v['id']}.json", v)
        return v


# ---------- кандидаты ----------

def papka(i):
    return ROOT / "kandidaty" / proverit_id(i)


def kandidat(i):
    return _chitat(papka(i) / "meta.json")


def spisok_kandidatov():
    root = ROOT / "kandidaty"
    out = [m for p in sorted(root.iterdir()) if (m := _chitat(p / "meta.json"))] if root.exists() else []
    return sorted(out, key=lambda k: k["sozdan"], reverse=True)


def novyy_kandidat(imya, vakansiya_id, status=OCHERED):
    m = {"id": novyy_id(), "imya": imya, "vakansiya_id": proverit_id(vakansiya_id), "soglasie": True,
         "sozdan": seychas(), "poryadok": time.time_ns(), "status": status, "oshibka": None, "faily": {}, "reshenie": None, "reshenie_data": None}
    with LOCK:
        _zapisat(papka(m["id"]) / "meta.json", m)
    return m


def obnovit_kandidata(i, **polya):
    with LOCK:
        m = kandidat(i)
        if m is None:
            raise KeyError(i)
        m.update(polya)
        _zapisat(papka(i) / "meta.json", m)
        return m


# ---------- правила (поправки HR) ----------

def pravila():
    return _chitat(ROOT / "pravila.json", [])


def dobavit_pravilo(text, vakansiya_id=None, iz_kandidata=None):
    with LOCK:
        p = pravila()
        r = {"id": novyy_id(), "text": text.strip(), "vakansiya_id": vakansiya_id, "iz_kandidata": iz_kandidata,
             "data": seychas()}
        p.append(r)
        _zapisat(ROOT / "pravila.json", p)
        zhurnal(f"правило добавлено {r['id']}")
        return r


def izmenit_pravilo(i, text):
    with LOCK:
        p = pravila()
        for r in p:
            if r["id"] == i:
                r["text"], r["izmeneno"] = text.strip(), seychas()
        _zapisat(ROOT / "pravila.json", p)


def udalit_pravilo(i):
    with LOCK:
        _zapisat(ROOT / "pravila.json", [r for r in pravila() if r["id"] != i])
        zhurnal(f"правило удалено {i}")


def pravila_dlya(vakansiya_id):
    """Общие правила + правила этой вакансии — списком для задания модели."""
    sp = [r for r in pravila() if r["vakansiya_id"] in (None, vakansiya_id)]
    return sp, "\n".join(f"- {r['text']}" for r in sp)
