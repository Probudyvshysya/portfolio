"""Заключение по собеседованию: профиль должности + расшифровка -> отчёт для HR.

Модель (локально, Ollama) отвечает строго по JSON-схеме, документ собирает код.
Решение по кандидату принимает человек (ст. 16 152-ФЗ) — отчёт только помогает.

  python otchet.py --profil profil.md --rasshifrovka sobes.rasshifrovka.txt -o sobes
  [--model qwen3:4b-instruct-2507-q4_K_M] [--cpu]  (--cpu = без видеокарты, как на офисном ПК)
Результат: sobes.otchet.md и sobes.otchet.json
"""

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = os.environ.get("HR_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
POTOKI = int(os.environ.get("HR_POTOKI", 4))  # щадящий режим, см. rasshifrovat.py
# Без этой строки 4B сначала «рассуждает» вне JSON-схемы (Ollama кладёт это в thinking), ответ вдвое длиннее,
# а иногда рассуждение не кончается и упирается в окно: пустой ответ (замер на RTX 4090, 19.10.2026).
# Рассуждает только главное заключение (zapros): так модель сама находит противоречия вроде «лично или по отделу».
# HR_RASSUZHDAT=1 возвращает рассуждение во все задания, для сравнения качества.
BEZ_RASSUZHDENIY = "\n\nОтвечай сразу JSON, без рассуждений и пояснений до него."
SRAZU_JSON = "" if os.environ.get("HR_RASSUZHDAT") == "1" else BEZ_RASSUZHDENIY
DLINA_ZAKLYUCHENIYA = 6144  # с рассуждением ответ 2,5–3,8 тыс. токенов; потолок не даёт зациклиться до конца окна
PRAVILA = Path(__file__).parent / "baza" / "pravila.md"

SHEMA = {
    "type": "object",
    "properties": {
        "kompetencii": {"type": "array", "items": {"type": "object", "properties": {
            "nazvanie": {"type": "string"},
            "ocenka": {"type": "string", "enum": ["сильно", "достаточно", "слабо", "нет данных"]},
            "pochemu": {"type": "string", "maxLength": 220},
            "citata": {"type": "string", "maxLength": 110},
            "taymkod": {"type": "string"},
        }, "required": ["nazvanie", "ocenka", "pochemu", "citata", "taymkod"]}},
        "zelenye_flagi": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "object", "properties": {
            "text": {"type": "string", "maxLength": 160}, "taymkod": {"type": "string"}}, "required": ["text", "taymkod"]}},
        "krasnye_flagi": {"type": "array", "items": {"type": "object", "properties": {
            "pravilo": {"type": "string", "maxLength": 120}, "fakt": {"type": "string", "maxLength": 160}, "taymkod": {"type": "string"}},
            "required": ["pravilo", "fakt", "taymkod"]}},
        "dengi": {"type": "object", "properties": {
            "ozhidaniya_rub": {"type": "integer"}, "vilka_max_rub": {"type": "integer"}, "taymkod": {"type": "string"}},
            "required": ["ozhidaniya_rub", "vilka_max_rub", "taymkod"]},
        "protivorechiya": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string", "maxLength": 300}, "taymkody": {"type": "string"}}, "required": ["text", "taymkody"]}},
        "voprosy_dalshe": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 160}},
        "vyvod": {"type": "string", "maxLength": 600},
        "sovet": {"type": "string", "enum": ["приглашать дальше", "под вопросом", "не подходит"]},
    },
    "required": ["kompetencii", "zelenye_flagi", "krasnye_flagi", "dengi", "protivorechiya", "voprosy_dalshe", "vyvod", "sovet"],
}

STIL = """Язык: простой живой русский, как опытный HR говорит коллеге. Глаголы вместо отглагольных существительных
(«проверил партию», а не «осуществил проверку партии»). Нельзя: «является», «данный», «в рамках», «осуществлять»,
«обеспечивать», «стоит отметить», длинное тире «—» (вместо него запятая или двоеточие), английские слова.
Короткие предложения, без воды и общих слов. О кандидате пиши «кандидат», без «он» и «она»: пол не угадывай."""

SYSTEM = """Ты помощник менеджера по персоналу. Тебе дают профиль должности и расшифровку собеседования.
Твоя задача — сверить ответы кандидата с профилем и подготовить материал для решения. Решение принимает человек.

Правила:
1. Оценивай только то, что кандидат сказал на собеседовании. Не додумывай.
2. Пройди ВСЕ компетенции из таблицы профиля, в том же порядке и с теми же названиями. Оценка:
   - «сильно» — ответ подробный и конкретный, уровень не ниже описанного в профиле как хороший;
   - «достаточно» — в целом соответствует, но без подробностей или с мелкими пробелами;
   - «слабо» — кандидат сам сказал, что не умеет / не делал, или ответ явно ниже уровня профиля;
   - «нет данных» — ТОЛЬКО если тему на собеседовании вообще не обсуждали.
3. Цитата — дословный кусок реплики кандидата, не длиннее 15 слов. Таймкод — [мм:сс] этой реплики.
4. Красный флаг — только по правилам из раздела «Красные флаги» профиля: pravilo — какое правило, fakt — что сказал
   кандидат, своими словами, одним предложением. Флаг по деньгам НЕ ставь: его считает программа по полю dengi.
5. dengi: ожидания кандидата и верх вилки из профиля, в рублях на руки, без бонусов (например 140000 и 120000).
   Если цифры не прозвучали — 0.
6. Противоречия — когда кандидат в разных местах называет несовместимые цифры или факты. Укажи все таймкоды.
7. Не оценивай эмоции, честность, характер, внешность, возраст, пол, семью, здоровье.
8. Вопросы на следующий этап — конкретные, по пробелам и противоречиям, не больше 5.
9. Вывод — ровно 3 предложения: сильные стороны, главные риски, что проверить дальше.
10. Пиши по-русски, коротко, без воды. Не упоминай веса компетенций.
11. Если говорящие подписаны «Голос 1», «Голос 2» — кандидат тот, кто отвечает на вопросы о своём опыте.
12. Поправки HR к прошлым отчётам важнее правил выше: это опыт этой компании.
13. Расшифровка сделана автоматически: термины и аббревиатуры могут быть искажены — понимай их по смыслу.

""" + STIL


def okno(*teksty, otvet=4096, minimum=8192):
    """Окно модели под длину разговора. Если вход не влезает, Ollama молча отрезает начало расшифровки.
    Русский текст у Qwen около 2,9 символа на токен, считаем по 2,5 с запасом."""
    n = int(sum(len(t) for t in teksty) / 2.5) + otvet
    return max(minimum, -(-n // 2048) * 2048)


def zapros(model, profil, rasshifrovka, pravila, cpu):
    user = f"# ПРОФИЛЬ ДОЛЖНОСТИ\n{profil}\n\n# РАСШИФРОВКА СОБЕСЕДОВАНИЯ\n{rasshifrovka}"
    if pravila:
        user = f"# ПОПРАВКИ HR К ПРОШЛЫМ ОТЧЁТАМ (соблюдать обязательно)\n{pravila}\n\n" + user
    # Сначала с рассуждением; если ответ сорвался (зациклилась и упёрлась в потолок), пересобираем без него
    for sistema in (SYSTEM, SYSTEM + BEZ_RASSUZHDENIY):
        body = {
            "model": model, "stream": False, "format": SHEMA,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": user}],
            "options": {"temperature": 0.1, "num_ctx": okno(SYSTEM, user, otvet=DLINA_ZAKLYUCHENIYA, minimum=16384),
                        "num_predict": DLINA_ZAKLYUCHENIYA, "num_thread": POTOKI, **({"num_gpu": 0} if cpu else {})},
        }
        req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3600) as r:
            res = json.load(r)
        try:
            o = json.loads(res["message"]["content"])
        except ValueError:
            continue
        if isinstance(o, dict):
            res["bez_rassuzhdeniya"] = sistema != SYSTEM
            return ochistit(o), res
    raise ValueError("модель дважды не вернула заключение; нажмите «Повторить разбор»")


CJK = re.compile(r"\s*[⺀-鿿가-힯぀-ヿ＀-￯]+\s*")


def ochistit(x):
    """Qwen изредка вставляет в русский текст китайские иероглифы — убираем из всех строк ответа."""
    if isinstance(x, str):
        return re.sub(r" {2,}", " ", CJK.sub(" ", x)).strip()
    if isinstance(x, list):
        return [ochistit(v) for v in x]
    if isinstance(x, dict):
        return {k: ochistit(v) for k, v in x.items()}
    return x


def kratko(t, n=105):
    """Цитату, обрезанную схемой, обрезаем по целому слову."""
    t = t.strip()
    return t if len(t) < n else t[:n].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def rub(x):
    return f"{x:,} ₽".replace(",", " ")


def proc(x):
    return f"{x:g}".replace(".", ",")


def porog_deneg(profil):
    m = re.search(r"выше вилки[^\n%]*?(\d+)\s*%", profil)
    return int(m.group(1)) if m else 20


def proverit_dengi(o, profil):
    """Процент превышения и флаг считает код: арифметику маленькой модели не доверяем."""
    d, porog = o.get("dengi") or {}, porog_deneg(profil)
    # флаги по деньгам от модели выкидываем — модель путается в процентах
    o["krasnye_flagi"] = [f for f in o["krasnye_flagi"]
                          if not re.search(r"вилк|зарплат|ожидани|деньг|оклад", f["pravilo"] + f["fakt"], re.I)]
    ozh, vmax = d.get("ozhidaniya_rub", 0), d.get("vilka_max_rub", 0)
    if ozh and vmax:
        pct = round((ozh - vmax) / vmax * 100, 1)
        d["prevyshenie_pct"], d["porog_pct"] = pct, porog
        if pct > porog:
            o["krasnye_flagi"].append({"pravilo": f"Ожидания выше вилки больше чем на {porog} %",
                                       "fakt": f"{rub(ozh)} при вилке до {rub(vmax)} (+{proc(pct)} %)",
                                       "taymkod": d.get("taymkod", "")})
    return o


LESENKA = ["не подходит", "под вопросом", "приглашать дальше"]
ZNACHENIE = {"сильно": 1.0, "достаточно": 0.6, "слабо": 0.0, "нет данных": 0.3}


def vesa_iz_profilya(profil):
    """Веса компетенций из таблицы профиля: строки «| Название | 3 | …»."""
    return {m.group(1).strip(): int(m.group(2)) for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([123])\s*\|", profil, re.M)}


def proverit_sovet(o, profil):
    """Балл по весам профиля считает код. Если совет модели расходится с ним на две ступени
    («приглашать дальше» при слабых оценках) — побеждает расчёт. На одну ступень — остаётся модели:
    там работают поправки HR."""
    import difflib

    vesa = vesa_iz_profilya(profil)
    summa = maks = 0.0
    ne_obsuzhdali, kluchevaya_bez_dannyh = [], False
    for k in o.get("kompetencii", []):
        nazv = k["nazvanie"]
        bliz = max(vesa, key=lambda v: difflib.SequenceMatcher(None, v.lower(), nazv.lower()).ratio(), default=None)
        w = vesa[bliz] if bliz and difflib.SequenceMatcher(None, bliz.lower(), nazv.lower()).ratio() > 0.6 else 1
        if k["ocenka"] == "нет данных":  # тему не обсуждали: кандидата за это не наказываем, а просим HR спросить
            ne_obsuzhdali.append(nazv)
            kluchevaya_bez_dannyh |= w == 3
            continue
        summa += w * ZNACHENIE.get(k["ocenka"], 0.3)
        maks += w
    ball = summa / maks if maks else 0
    # деньги — условие, а не деловое качество: флаг виден HR, но к «не подходит» не ведёт
    n = len([f for f in o.get("krasnye_flagi", []) if not re.search(r"вилк|ожидани", f.get("pravilo", ""), re.I)])
    n_vse = len(o.get("krasnye_flagi", []))
    # «приглашать дальше» — только если все ключевые (вес 3) не ниже «достаточно» и главное требование руководителя
    # не под риском; иначе «под вопросом» с причиной: решает HR
    pochemu_ne = []
    for k in o.get("kompetencii", []):
        bliz = max(vesa, key=lambda v: difflib.SequenceMatcher(None, v.lower(), k["nazvanie"].lower()).ratio(), default=None)
        if bliz and vesa[bliz] == 3 and k["ocenka"] == "слабо":
            pochemu_ne.append(f"ключевая компетенция «{k['nazvanie']}» слабо")
    if kluchevaya_bez_dannyh:
        pochemu_ne.append("ключевую компетенцию не обсуждали")
    if (o.get("glavnoe") or {}).get("status") == "риск":
        pochemu_ne.append("риск по главному требованию руководителя")
    raschet = "не подходит" if ball < 0.45 or n >= 3 else (
        "приглашать дальше" if ball >= 0.75 and n_vse == 0 and not pochemu_ne else "под вопросом")
    o["ball_pct"], o["sovet_raschet"], o["ne_obsuzhdali"] = round(ball * 100), raschet, ne_obsuzhdali
    o["pochemu_ne_dalshe"] = pochemu_ne if raschet == "под вопросом" and ball >= 0.75 and n_vse == 0 else []
    yavno = (ball >= 0.9 and n == 0) or ball < 0.25  # по краям шкалы сомнений нет — решает расчёт
    if o.get("sovet") in LESENKA and o["sovet"] != raschet and (yavno or abs(LESENKA.index(o["sovet"]) - LESENKA.index(raschet)) == 2):
        o["sovet_modeli"], o["sovet"] = o["sovet"], raschet
    # ожидания по деньгам — отдельный блок, не «противоречие»
    # и выводы «нет противоречия» — маленькая модель иногда кладёт их в этот же список
    o["protivorechiya"] = [x for x in o.get("protivorechiya", [])
                           if not re.search(r"вилк|зарплат|ожидани|₽|руб|нет противоречи|не противоречит|согласуется",
                                            x.get("text", ""), re.I)]
    return o


def v_markdown(o, imya):
    znak = {"сильно": "🟢", "достаточно": "🟡", "слабо": "🔴", "нет данных": "⚪"}
    L = [f"# Заключение по собеседованию: {imya}", "",
         f"**Совет помощника:** {o['sovet']} · балл по профилю {o.get('ball_pct', '—')} % · решение принимает HR",
         "", "## Вывод", o["vyvod"], ""]
    g = o.get("glavnoe")
    if g:
        L += [f"**Главное требование руководителя:** {g['trebovanie']} — {g['status']}. {g['poyasnenie']}"
              + (f" ({g['taymkod']})" if g.get("taymkod") else ""), ""]
    if o.get("ne_obsuzhdali"):
        L += ["**Не обсуждали, спросить на следующем этапе:** " + ", ".join(o["ne_obsuzhdali"]), ""]
    L += ["## Компетенции", "| | Компетенция | Оценка | Почему | Цитата | Время |", "|---|---|---|---|---|---|"]
    for k in o["kompetencii"]:
        L.append(f"| {znak.get(k['ocenka'], '')} | {k['nazvanie']} | {k['ocenka']} | {k['pochemu']} | «{kratko(k['citata'])}» | {k['taymkod']} |")
    L += ["", "## Зелёные флаги"] + ([f"- {x['text']} ({x['taymkod']})" for x in o["zelenye_flagi"]] or ["- нет"])
    L += ["", "## Красные флаги"] + ([f"- **{x['pravilo']}** — {x['fakt']} ({x['taymkod']})" for x in o["krasnye_flagi"]] or ["- нет"])
    d = o.get("dengi") or {}
    if "prevyshenie_pct" in d:
        L += ["", f"**Деньги:** ожидания {rub(d['ozhidaniya_rub'])}, вилка до {rub(d['vilka_max_rub'])} — "
              f"{'+' if d['prevyshenie_pct'] > 0 else ''}{proc(d['prevyshenie_pct'])} % "
              f"(порог флага {d['porog_pct']} %, посчитано программой) ({d.get('taymkod', '')})"]
    L += ["", "## Противоречия"] + ([f"- {x['text']} ({x['taymkody']})" for x in o["protivorechiya"]] or ["- нет"])
    pf = o.get("proverka_faktov") or []
    if pf:
        znak_p = {"подтверждено": "✅", "неверно": "❌", "спорно": "⚠", "не проверено": "⚪"}
        L += ["", "## Проверка фактов (база знаний и интернет)"]
        for x in pf:
            ist = x.get("istochnik") or {}
            ssylka = f" — {ist.get('dokument', '')}, {ist.get('razdel', '')}".rstrip(", ") if ist else ""
            L.append(f"- {znak_p.get(x['verdikt'], '')} **{x['fakt']}** ({x['taymkod']}): {x['verdikt']}{ssylka}. {x['poyasnenie']}")
    L += ["", "## Вопросы на следующий этап"] + [f"{i}. {q}" for i, q in enumerate(o["voprosy_dalshe"], 1)]
    L += ["", "---", "_Не оценивались: эмоции, честность, характер — по голосу это ненадёжно._"]
    return "\n".join(L) + "\n"


def dovesti(o, profil, rasshifrovka):
    """Доводка кодом (hr/dovodka.py) + совет по весам. Запускается после модели и ещё раз после проверки фактов."""
    from hr import dovodka
    from hr.plan import krasnye_flagi

    o = dovodka.dovesti(o, profil, rasshifrovka, krasnye_flagi(profil))
    return proverit_sovet(o, profil)


def sverit_citaty(o, rasshifrovka):
    """Каждую цитату кандидата ищем в расшифровке: если модель приписала человеку слова, HR это увидит."""
    from hr.yazyk import est_v_tekste

    for k in o.get("kompetencii", []):
        k["citata_proverena"] = bool(k.get("citata")) and est_v_tekste(k["citata"], rasshifrovka)
    return o


def sostavit(profil, rasshifrovka, pravila="", model=MODEL, cpu=False):
    """Главная функция для импорта: (заключение, замер)."""
    t0 = time.perf_counter()
    o, raw = zapros(model, profil, rasshifrovka, pravila, cpu)
    from hr.yazyk import k_vy, ochelovechit, po_russki

    from hr import dovodka

    o = proverit_dengi(o, profil)
    try:  # противоречия в цифрах — отдельным узким проходом (модель в общем ответе их пропускает)
        naydeno = dovodka.naiti_protivorechiya(rasshifrovka, model, OLLAMA, POTOKI)
    except OSError:
        naydeno = []
    try:  # главное требование руководителя — тоже отдельным узким проходом
        o["glavnoe"] = dovodka.proverit_glavnoe(rasshifrovka, profil, model, OLLAMA, POTOKI)
    except (OSError, ValueError):  # ValueError: модель сорвалась в ответе — заключение отдаём без этого блока
        o["glavnoe"] = None
    zanyato = {x["taymkody"] for x in naydeno}
    o["protivorechiya"] = naydeno + [x for x in o.get("protivorechiya", []) if x.get("taymkody") not in zanyato]
    o = ochelovechit(o)
    o["voprosy_dalshe"] = [k_vy(q) for q in o.get("voprosy_dalshe", []) if po_russki(q)]
    o = dovesti(o, profil, rasshifrovka)
    zamer = {"model": model, "cpu": cpu, "vremya_s": round(time.perf_counter() - t0, 1),
             "tokenov_vhod": raw.get("prompt_eval_count"), "tokenov_vyhod": raw.get("eval_count"),
             "bez_rassuzhdeniya": raw.get("bez_rassuzhdeniya"),
             "vremya_modeli_s": round(raw.get("total_duration", 0) / 1e9, 1)}
    return o, zamer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profil", required=True)
    ap.add_argument("--rasshifrovka", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--imya", default="кандидат")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--cpu", action="store_true")
    a = ap.parse_args()

    pravila = PRAVILA.read_text(encoding="utf-8") if PRAVILA.exists() else ""
    o, zamer = sostavit(Path(a.profil).read_text(encoding="utf-8"),
                        Path(a.rasshifrovka).read_text(encoding="utf-8"), pravila, a.model, a.cpu)
    Path(a.out + ".otchet.json").write_text(json.dumps({"zamer": zamer, "otchet": o}, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(a.out + ".otchet.md").write_text(v_markdown(o, a.imya), encoding="utf-8")
    print(json.dumps(zamer, ensure_ascii=False))


if __name__ == "__main__":
    main()
