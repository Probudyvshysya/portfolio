"""База знаний компании: документы из папки znaniya/ (ГОСТы, регламенты) + поиск по смыслу (bge-m3 в Ollama).

Документ = файл .md или .txt. В .md кусок = раздел «## …» — так ссылка ведёт на конкретный пункт.
Индекс (куски + векторы) — znaniya/indeks.json, пересобирается сам, если документы изменились.
"""

import hashlib
import json
import math
import re
import urllib.request
from pathlib import Path

PAPKA = Path(__file__).resolve().parent.parent / "znaniya"
EMBED = "http://127.0.0.1:11434/api/embed"
MODEL_EMB = "bge-m3"


def _vektora(teksty):
    body = json.dumps({"model": MODEL_EMB, "input": teksty}).encode()
    req = urllib.request.Request(EMBED, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["embeddings"]


def _kuski(path):
    text = path.read_text(encoding="utf-8")
    zag = (re.search(r"^# (.+)$", text, re.M) or [None, path.stem])[1]
    if path.suffix == ".md":
        chasti = re.split(r"^## ", text, flags=re.M)
        out = []
        for ch in chasti[1:]:
            razdel, _, telo = ch.partition("\n")
            out.append({"dokument": zag, "fayl": path.name, "razdel": razdel.strip(), "text": telo.strip()})
        return out or [{"dokument": zag, "fayl": path.name, "razdel": "", "text": text.strip()}]
    # .txt — абзацами по ~700 символов
    abzacy, buf, out = [a.strip() for a in text.split("\n") if a.strip()], "", []
    for a in abzacy:
        if len(buf) + len(a) > 700 and buf:
            out.append(buf)
            buf = ""
        buf += a + "\n"
    if buf:
        out.append(buf)
    return [{"dokument": zag, "fayl": path.name, "razdel": "", "text": t} for t in out]


def dokumenty(papka=None):
    papka = papka or PAPKA
    # словарь замен распознавания — служебный файл, не документ базы
    return sorted(p for p in papka.glob("*") if p.suffix in (".md", ".txt") and p.is_file()
                  and not p.name.startswith("slovar"))


def _otpechatok(files):
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()


def indeks(papka=None, vektora=_vektora):
    """Индекс базы; пересобирается, если документы поменялись."""
    papka = papka or PAPKA
    files = dokumenty(papka)
    put = papka / "indeks.json"
    ot = _otpechatok(files)
    try:
        ix = json.loads(put.read_text(encoding="utf-8"))
        if ix["otpechatok"] == ot:
            return ix
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        pass
    kuski = [k for f in files for k in _kuski(f)]
    vv = vektora([f"{k['dokument']}. {k['razdel']}. {k['text']}" for k in kuski]) if kuski else []
    for k, v in zip(kuski, vv):
        k["v"] = v
    ix = {"otpechatok": ot, "kuski": kuski}
    put.write_text(json.dumps(ix, ensure_ascii=False), encoding="utf-8")
    return ix


def _cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    return num / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def iskat(zapros, k=3, papka=None, vektora=_vektora):
    """Лучшие куски базы по смыслу: [{dokument, razdel, text, ball}]."""
    ix = indeks(papka, vektora)
    if not ix["kuski"]:
        return []
    q = vektora([zapros])[0]
    res = sorted(({**{x: c[x] for x in ("dokument", "fayl", "razdel", "text")}, "ball": round(_cos(q, c["v"]), 3)}
                  for c in ix["kuski"]), key=lambda c: -c["ball"])
    return res[:k]
