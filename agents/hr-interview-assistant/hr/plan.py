"""План собеседования по профилю вакансии: HR идёт на созвон с готовыми вопросами.

Модель пишет только вопросы и тревожные сигналы. «Что считаем хорошим ответом» берётся дословно из профиля,
время по блокам и юридические ограничения считает код — их модели не доверяем.
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT_KOMPLEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_KOMPLEKT))
from otchet import MODEL, OLLAMA, POTOKI, SRAZU_JSON, STIL, ochistit, porog_deneg  # noqa: E402

from .yazyk import k_vy, ochelovechit, po_russki, vychitat  # noqa: E402

MINUT_NA_KOMPETENCII = 35  # остальное время созвона — знакомство, вопросы кандидата, деньги

SHEMA = {
    "type": "object",
    "properties": {
        "bloki": {"type": "array", "items": {"type": "object", "properties": {
            "kompetenciya": {"type": "string"},
            "voprosy": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string", "maxLength": 200}},
            "utochnenie": {"type": "string", "maxLength": 200},
            "trevozhnyy_signal": {"type": "string", "maxLength": 200},
        }, "required": ["kompetenciya", "voprosy", "utochnenie", "trevozhnyy_signal"]}},
        "flagi": {"type": "array", "items": {"type": "object", "properties": {
            "flag": {"type": "string"}, "vopros": {"type": "string", "maxLength": 200}}, "required": ["flag", "vopros"]}},
    },
    "required": ["bloki", "flagi"],
}

SYSTEM = """Ты помогаешь менеджеру по персоналу подготовиться к собеседованию. Тебе дают профиль должности.
Составь вопросы, чтобы за один созвон проверить каждую компетенцию из таблицы профиля.

Правила:
1. Пройди ВСЕ компетенции из таблицы профиля, в том же порядке и с теми же названиями.
2. По каждой — 2 вопроса о прошлом опыте кандидата: «расскажите, как вы…», «приведите случай, когда…»,
   «сколько / какие именно…». Не гипотетические «что бы вы сделали», а что он делал на самом деле.
   Вопрос должен проверять именно то, что в профиле написано как хороший уровень.
3. Не придумывай цифры, пороги и объёмы, которых нет в профиле. Если хороший уровень — срок или число (сколько лет,
   сколько поставщиков), спроси прямо: «Сколько лет вы проработали на последнем месте?», без «приведите пример».
   Про уход с работы спрашивай о работе (что изменилось, чего не хватало), не о личной жизни.
4. utochnenie — один уточняющий вопрос по ЭТОЙ ЖЕ компетенции, если ответ общий: просит цифры, названия, результат.
5. trevozhnyy_signal — какой ответ показывает, что уровня нет, по ЭТОЙ компетенции. Пиши о кандидате в третьем лице,
   одним предложением, начиная с глагола в настоящем времени. Не обращайся к кандидату на «вы» в этом поле.
6. flagi — по каждому красному флагу из профиля, КРОМЕ флага про деньги, — один вопрос, который его проверяет.
   flag — название флага как в профиле.
7. Не спрашивай про возраст, семью, детей, беременность, здоровье, национальность, религию, политику.
8. В вопросах обращайся к кандидату на «вы».

""" + STIL

NELZYA = [
    "Возраст, семейное положение, дети и планы на них, беременность",
    "Здоровье и инвалидность (кроме ограничений, прямо связанных с работой)",
    "Национальность, религия, политические взгляды, членство в профсоюзе",
    "Место жительства и прописка как условие найма",
]
NELZYA_POCHEMU = ("ст. 3 и 64 ТК РФ запрещают отказывать по обстоятельствам, не связанным с деловыми качествами; "
                  "ст. 86 ТК — работодатель не вправе собирать сведения о частной жизни, политике и религии")


def kompetencii_profilya(profil):
    """Строки таблицы профиля: (название, вес, что считаем хорошим уровнем)."""
    return [(m.group(1).strip(), int(m.group(2)), m.group(3).strip())
            for m in re.finditer(r"^\|\s*([^|\n]+?)\s*\|\s*([123])\s*\|\s*([^|\n]*?)\s*\|", profil, re.M)]


def krasnye_flagi(profil):
    m = re.search(r"^## Красные флаги\s*\n(.*?)(?=^## |\Z)", profil, re.M | re.S)
    return [s.strip("-• ").strip() for s in (m.group(1).splitlines() if m else []) if s.strip().startswith(("-", "•"))]


def vilka(profil):
    m = re.search(r"Вилка:\s*([^\n]+)", profil)
    return m.group(1).strip() if m else ""


def raspredelit_vremya(vesa, vsego=MINUT_NA_KOMPETENCII):
    """Минуты на блок пропорционально весу, не меньше 2, кратно 1."""
    s = sum(vesa) or 1
    return [max(2, round(vsego * w / s)) for w in vesa]


def sobrat_plan(otvet, profil):
    """Склеивает ответ модели с профилем: хороший уровень и веса — из профиля, порядок — как в профиле."""
    import difflib

    komp = kompetencii_profilya(profil)
    bloki_modeli = otvet.get("bloki", [])

    def blok_dlya(nazv):
        imena = [b["kompetenciya"] for b in bloki_modeli]
        bliz = difflib.get_close_matches(nazv, imena, n=1, cutoff=0.5)
        return next((b for b in bloki_modeli if bliz and b["kompetenciya"] == bliz[0]), None)

    minuty = raspredelit_vremya([w for _, w, _ in komp])
    bloki = []
    for (nazv, ves, horosho), mins in zip(komp, minuty):
        b = blok_dlya(nazv) or {}
        b = {**b, "voprosy": [q for q in b.get("voprosy") or [] if po_russki(q)]}
        if "лет на месте" in horosho:  # модель упорно пишет «приведите случай, когда вы оставались больше 1,5 лет»
            pryamoy = "Сколько вы проработали на последнем месте и на предыдущем?"
            vopr = [q for q in b["voprosy"] if not re.search(r"оставал\w* на работе|приведите (?:случай|пример), когда вы оставал", q, re.I)]
            b["voprosy"] = vopr + ([pryamoy] if len(vopr) < len(b["voprosy"]) or not vopr else [])
        bloki.append({"kompetenciya": nazv, "ves": ves, "minut": mins, "horoshiy_otvet": horosho,
                      "voprosy": b.get("voprosy") or [], "utochnenie": b.get("utochnenie", ""),
                      "trevozhnyy_signal": b.get("trevozhnyy_signal", "")})
    flagi = [f for f in otvet.get("flagi", []) if not re.search(r"вилк|деньг|ожидани|зарплат", f.get("flag", ""), re.I)]
    porog = porog_deneg(profil)
    dengi = {"vopros": "Какие у вас ожидания по доходу на руки? Из чего складывается доход сейчас: оклад, бонус?",
             "vilka": vilka(profil), "porog_pct": porog}
    return {"bloki": bloki, "flagi": flagi, "dengi": dengi, "nelzya": NELZYA, "nelzya_pochemu": NELZYA_POCHEMU,
            "minut_vsego": sum(minuty) + 10}


def shema_dlya(profil):
    """Схема под конкретный профиль: ровно столько блоков, сколько компетенций, названия — только из профиля.
    Без этого маленькая модель при температуре 0 может вернуть пустые списки или переименовать компетенцию."""
    import copy

    sh = copy.deepcopy(SHEMA)
    imena = [k for k, _, _ in kompetencii_profilya(profil)]
    bl = sh["properties"]["bloki"]
    bl["minItems"] = bl["maxItems"] = len(imena)
    bl["items"]["properties"]["kompetenciya"]["enum"] = imena
    flagi = [f for f in krasnye_flagi(profil) if not re.search(r"вилк|деньг|ожидани|зарплат", f, re.I)]
    fl = sh["properties"]["flagi"]
    if flagi:
        fl["minItems"] = fl["maxItems"] = len(flagi)
        fl["items"]["properties"]["flag"]["enum"] = flagi
    else:
        fl["maxItems"] = 0
    return sh


def sostavit(profil, model=MODEL):
    if not kompetencii_profilya(profil):
        raise ValueError("в профиле нет таблицы компетенций — сначала соберите профиль")
    t0 = time.perf_counter()
    body = {"model": model, "stream": False, "format": shema_dlya(profil),
            "messages": [{"role": "system", "content": SYSTEM + SRAZU_JSON}, {"role": "user", "content": f"# ПРОФИЛЬ ДОЛЖНОСТИ\n{profil}"}],
            "options": {"temperature": 0, "num_ctx": 8192, "num_thread": POTOKI}}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        otvet = ochelovechit(ochistit(json.loads(json.load(r)["message"]["content"])))
    # вычитка вторым проходом: все фразы плана одним списком, назад по тем же местам
    mesta = [(b, "voprosy", n) for b in otvet.get("bloki", []) for n in range(len(b.get("voprosy", [])))]
    mesta += [(b, k, None) for b in otvet.get("bloki", []) for k in ("utochnenie", "trevozhnyy_signal") if b.get(k)]
    mesta += [(f, "vopros", None) for f in otvet.get("flagi", []) if f.get("vopros")]
    berem = lambda d, k, n: d[k][n] if n is not None else d[k]  # noqa: E731
    try:
        novye = vychitat([berem(d, k, n) for d, k, n in mesta], model)
        for (d, k, n), t in zip(mesta, novye):
            if n is None:
                d[k] = t
            else:
                d[k][n] = t
    except OSError:
        pass  # вычитка — улучшение; без неё план всё равно годный
    for d, k, n in mesta:  # всё это вопросы кандидату, кроме тревожного сигнала (он про кандидата, в третьем лице)
        if k != "trevozhnyy_signal":
            if n is None:
                d[k] = k_vy(d[k])
            else:
                d[k][n] = k_vy(d[k][n])
    plan = sobrat_plan(otvet, profil)
    plan["zamer"] = {"model": model, "vremya_s": round(time.perf_counter() - t0, 1)}
    return plan
