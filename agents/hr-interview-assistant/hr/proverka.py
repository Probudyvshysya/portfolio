"""Проверка фактов: что кандидат сказал о нормах, ГОСТах, законах — сверяем с базой знаний и (если не нашли) с интернетом.

Шаги: модель выписывает проверяемые утверждения → программа ищет текст (база, потом интернет) →
модель по найденному тексту ставит вердикт со ссылкой на источник. Без источника — «не проверено».

В интернет уходит только общий вопрос: без имени кандидата, без цифр-идентификаторов, без цитат.
Каждый запрос наружу — в журнал dannye/vyhod.log (вкладка «Безопасность»).
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

from . import hranilishche as H
from . import znaniya

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from otchet import MODEL, OLLAMA, POTOKI, SRAZU_JSON, ochistit, okno  # noqa: E402

POROG_BAZY = 0.55  # ниже — в базе ничего подходящего, идём в интернет

SHEMA_UTV = {"type": "object", "properties": {"utverzhdeniya": {"type": "array", "maxItems": 4, "items": {
    "type": "object", "properties": {
        "citata": {"type": "string", "maxLength": 160},
        "taymkod": {"type": "string"},
        "fakt": {"type": "string", "maxLength": 160},
        "zapros": {"type": "string", "maxLength": 100}},
    "required": ["citata", "taymkod", "fakt", "zapros"]}}}, "required": ["utverzhdeniya"]}

# порядок полей = порядок «мысли» модели: сначала выписать, что в источнике, потом сравнить
SHEMA_VERDIKT = {"type": "object", "properties": {
    "istochnik_nomer": {"type": "integer"},
    "chto_v_istochnike": {"type": "string", "maxLength": 250},
    "verdikt": {"type": "string", "enum": ["подтверждено", "неверно", "не проверено"]},  # + «спорно» (ставит код)
    "poyasnenie": {"type": "string", "maxLength": 250}},
    "required": ["istochnik_nomer", "chto_v_istochnike", "verdikt", "poyasnenie"]}

SYS_UTV = """Найди в расшифровке собеседования утверждения КАНДИДАТА об общих фактах, которые можно проверить по
ГОСТу, закону или нормативу: нормы показателей качества зерна, классы, обязательные документы, налоговые правила.
НЕ бери: личный опыт и истории («я закупал», «у нас делала бухгалтерия», «в Экселе у меня таблица»),
коммерческую практику компании, мнения. Не больше 4. Если таких нет — пустой список.
fakt — ОДИН простой факт своими словами, без истории вокруг, например:
«Клейковина 21 % соответствует 4 классу мягкой пшеницы» или «Влажность пшеницы по ГОСТ — не более 14 %».
zapros — короткий поисковый запрос по сути факта, без имён и личных данных."""

SYS_VERDIKT = """Проверь ОДИН факт по тексту источников. Опирайся только на источники, не на память.
Сначала выпиши в chto_v_istochnike точную норму из источника (с цифрами). Потом сравни с фактом:
«подтверждено» — норма из источника согласуется с фактом; «неверно» — норма прямо противоречит факту
(например, кандидат назвал 20 %, а в источнике 23 %); «не проверено» — в источниках этой нормы нет.
Если факт согласуется с нормой — это «подтверждено», даже если сказано другими словами."""


def _chat(system, user, shema, num_ctx=8192):
    body = {"model": MODEL, "stream": False, "format": shema,
            "messages": [{"role": "system", "content": system + SRAZU_JSON}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "num_ctx": num_ctx, "num_thread": POTOKI}}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return ochistit(json.loads(json.load(r)["message"]["content"]))


def obezlichit(zapros, imya=""):
    """Фильтр перед выходом в интернет: убираем имя кандидата, длинные числа (ИНН, телефоны), почту."""
    q = zapros
    for slovo in re.findall(r"\w{3,}", imya or ""):
        q = re.sub(rf"\b{re.escape(slovo)}\w*", "", q, flags=re.I)
    q = re.sub(r"\S+@\S+", "", q)
    q = re.sub(r"\+?\d[\d\s()-]{8,}\d", "", q)  # телефоны, ИНН, счета
    return re.sub(r"\s+", " ", q).strip()[:100]


def iskat_v_internete(zapros, n=3):
    from ddgs import DDGS

    res = DDGS().text(zapros, region="ru-ru", max_results=n)
    return [{"dokument": r.get("title", ""), "razdel": r.get("href", ""), "text": r.get("body", ""), "url": r.get("href", "")}
            for r in res]


def raskhodyatsya_cifry(fakt, istochnik):
    """Есть ли в словах кандидата число, которого нет в норме источника."""
    def chisla(t):  # «23,0» и «23» — одно число
        return {f"{float(x.replace(',', '.')):g}" for x in re.findall(r"\d+(?:[.,]\d+)?", t)}

    u = chisla(fakt)
    return bool(u) and bool(u - chisla(istochnik))


def bez_dubley(utv):
    """Один и тот же факт, сказанный дважды, — одна строка с несколькими таймкодами."""
    import difflib

    out = []
    for u in utv:
        norm = re.sub(r"[^\w%]+", " ", u["fakt"].lower()).strip()
        for o in out:
            if difflib.SequenceMatcher(None, norm, o["_norm"]).ratio() > 0.85:
                if u["taymkod"] and u["taymkod"] not in o["taymkod"]:
                    o["taymkod"] += ", " + u["taymkod"]
                break
        else:
            out.append({**u, "_norm": norm})
    return [{k: v for k, v in o.items() if k != "_norm"} for o in out]


def proverit(tekst, imya="", internet=True, iskat_bazu=None, iskat_set=None, chat=None):
    """Возвращает список [{citata, fakt, taymkod, verdikt, poyasnenie, istochnik{...}, gde: база|интернет|—}]."""
    iskat_bazu = iskat_bazu or znaniya.iskat
    iskat_set = iskat_set or iskat_v_internete
    chat = chat or _chat
    utv = bez_dubley(chat(SYS_UTV, tekst, SHEMA_UTV, okno(SYS_UTV, tekst, minimum=16384)).get("utverzhdeniya", []))
    out = []
    for u in utv:
        nayd = [x for x in iskat_bazu(u["zapros"]) if x.get("ball", 1) >= POROG_BAZY]
        gde = "база" if nayd else "—"
        if not nayd and internet:
            q = obezlichit(u["zapros"], imya)
            try:
                nayd = iskat_set(q)
                gde = "интернет"
                H.zhurnal_vyhoda(f"поиск: «{q}» → найдено: {len(nayd)}")
            except Exception as e:
                H.zhurnal_vyhoda(f"поиск: «{q}» → ошибка {type(e).__name__}")
        if not nayd:
            out.append({**u, "verdikt": "не проверено", "poyasnenie": "источник не найден", "istochnik": None, "gde": "—"})
            continue
        istochniki = "\n\n".join(f"[{i}] {x['dokument']} — {x['razdel']}\n{x['text']}" for i, x in enumerate(nayd, 1))
        v = chat(SYS_VERDIKT, f"ФАКТ: {u['fakt']}\n\nИСТОЧНИКИ:\n{istochniki}", SHEMA_VERDIKT)
        n = v.get("istochnik_nomer", 0)
        ist = nayd[n - 1] if 1 <= n <= len(nayd) else None
        if v["verdikt"] != "не проверено" and ist is None:  # вердикт без источника не принимаем
            v["verdikt"], v["poyasnenie"] = "не проверено", "модель не указала источник"
        if gde == "база" and v["verdikt"] == "неверно" and not raskhodyatsya_cifry(u["fakt"], v["chto_v_istochnike"]):
            # «кандидат ошибся» по базе — только когда его цифры расходятся с цифрами документа
            v["verdikt"] = "спорно"
            v["poyasnenie"] = "Похоже на расхождение с документом, но без цифр — проверьте сами. " + v["poyasnenie"]
        if gde == "интернет" and v["verdikt"] == "неверно":
            # «кандидат ошибся» — только по документам из базы; статья из интернета может быть неточной сама
            v["verdikt"] = "спорно"
            v["poyasnenie"] = "Источник из интернета расходится со словами кандидата — проверьте по ссылке. " + v["poyasnenie"]
        out.append({**u, "verdikt": v["verdikt"], "poyasnenie": v["poyasnenie"], "v_istochnike": v["chto_v_istochnike"],
                    "gde": gde if ist else "—",
                    "istochnik": {k: ist.get(k, "") for k in ("dokument", "razdel", "url", "text")} if ist else None})
    return out
