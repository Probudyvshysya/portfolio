"""Доводка заключения кодом — после модели и после проверки фактов. Здесь закрыты дыры, которые нашла внешняя
проверка 19.10.2026 (Z.ai по заданию demo/ZADANIE-razgrom.md, каждое замечание сверено с расшифровками):

- противоречия в цифрах ищет отдельный узкий проход по местам разговора, где звучат цифры
  (Игорь: «я один закупал 120 000 т» и «это по отделу, я вёл треть» модель назвала «цифры согласуются»);
- цитаты и таймкоды берутся из расшифровки, а не из ответа модели (у Ольги СДИЗ стоял на 00:29 вместо 01:29);
- если кандидат ошибся в норме (проверка фактов «неверно»), оценка компетенции в этом месте снижается на ступень,
  а зелёный флаг в этом месте снимается (Денис: ошибка в ГОСТе, а знание качества «достаточно» и зелёный флаг);
- вопросы на следующий этап не повторяют то, что уже спрашивали, и не берутся из вопросов самого кандидата;
- «противоречие» без двух мест разговора — не противоречие.

Всё идемпотентно: доводку можно запускать повторно на готовом заключении.
"""

import json
import re
import urllib.request

from .yazyk import est_v_tekste, norm

STROKA = re.compile(r"^\[(\d+):(\d\d)\]\s*([^:]+):\s*(.*)$")
LESENKA_OCENOK = ["слабо", "достаточно", "сильно"]


def repliki(rasshifrovka):
    out = []
    for s in rasshifrovka.splitlines():
        m = STROKA.match(s.strip())
        if m:
            out.append({"tc": f"{m.group(1)}:{m.group(2)}", "kto": m.group(3).strip(), "text": m.group(4).strip()})
    return out


def kandidat_li(kto):
    return not re.match(r"HR|Голос 1$", kto, re.I)


# ---------- противоречия: узкий проход ----------

SHEMA_PROTIV = {"type": "object", "properties": {"protivorechiya": {"type": "array", "maxItems": 3, "items": {
    "type": "object", "properties": {"pervoe": {"type": "string"}, "vtoroe": {"type": "string"},
                                     "text": {"type": "string", "maxLength": 300}},
    "required": ["pervoe", "vtoroe", "text"]}}}, "required": ["protivorechiya"]}

SYSTEM_PROTIV = """Ты проверяешь собеседование на противоречия. Тебе дают только те места разговора, где звучат цифры.
Найди, где кандидат сам себе противоречит: про одно и то же говорит по-разному. Например, сначала «я один закупал
столько-то», потом «это было на весь отдел»; разные объёмы, сроки, число поставщиков про одно и то же.
Разные вещи (объём за сезон и число хозяйств, два разных года) — не противоречие.
Для каждого противоречия: pervoe и vtoroe — таймкоды двух мест в формате мм:сс, text — одно-два предложения,
что сказано в первом месте и что во втором. Если противоречий нет — пустой список. Пиши по-русски."""


def mesta_s_ciframi(reps):
    """Ответы кандидата, где цифры есть в самом ответе или в вопросе HR перед ним, — вместе с этим вопросом."""
    out = []
    for i, r in enumerate(reps):
        if not kandidat_li(r["kto"]):
            continue
        vopros = reps[i - 1] if i and not kandidat_li(reps[i - 1]["kto"]) else None
        if re.search(r"\d", r["text"]) or (vopros and re.search(r"\d", vopros["text"])):
            out.append((r, vopros))
    return out


VELICHINY = {"объём": r"тонн|тон\b|\bт\b|тыс\.?\s*т", "поставщики": r"хозяйств|поставщик|фермер",
             "срок": r"\bлет\b|\bгод|месяц", "деньги": r"₽|руб|тысяч|тыс\b"}

SHEMA_PARA = {"type": "object", "properties": {"odno_i_to_zhe": {"type": "boolean"}, "protivorechie": {"type": "boolean"},
                                               "text": {"type": "string", "maxLength": 300}},
              "required": ["odno_i_to_zhe", "protivorechie", "text"]}

SYSTEM_PARA = """Тебе дают два места из собеседования. Ответь на два вопроса.
1. odno_i_to_zhe: в обоих местах кандидат говорит про одну и ту же вещь (тот же объём, тот же срок, то же число)?
   Объём за сезон и объём одной сделки — разные вещи. Прошлый сезон и хороший сезон — может быть одно и то же.
2. protivorechie: если вещь одна, кандидат описывает её по-разному так, что оба утверждения не могут быть правдой?
   Например: «я сам вёл 40 хозяйств» и «40 хозяйств было у всей команды, у меня около десяти» — противоречие.
text: одно-два предложения, что сказано в первом месте и что во втором. По-русски."""


def velichina(t):
    return {k for k, rx in VELICHINY.items() if re.search(rx, t, re.I)}


LICHNO = r"\bя (?:один|одна|сам|сама)\b|\bлично\b|\bмой (?:объём|результат)\b"
KOMANDA = r"\bотдел|\bнас (?:двое|трое|четверо|пятеро|было)|\bкоманд|\bв целом\b|\bвсего по\b|\bвсе вместе\b"


def kratko(t, n=120):
    t = t.strip()
    t = t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"
    return t.rstrip(".")


def chisla(t):
    """Числа от 10 и больше, без пробелов внутри: «120 000» -> «120000»."""
    return {re.sub(r"\s", "", m) for m in re.findall(r"\d[\d\s]{1,}\d|\d{2,}", t)}


def lichnoe_protiv_komandnogo(mesta):
    """Правило кодом: одна и та же цифра в двух местах, в одном «я один / сам», в другом «отдел / нас трое / в целом».
    Типичное противоречие на собеседовании: человек приписывает себе результат команды."""
    out = []
    for i in range(len(mesta)):
        for j in range(i + 1, len(mesta)):
            (ra, va), (rb, vb) = mesta[i], mesta[j]
            ta = (va["text"] + " " if va else "") + ra["text"]
            tb = (vb["text"] + " " if vb else "") + rb["text"]
            if not chisla(ta) & chisla(tb):
                continue
            for (r1, t1), (r2, t2) in (((ra, ta), (rb, tb)), ((rb, tb), (ra, ta))):
                if re.search(LICHNO, r1["text"], re.I) and re.search(KOMANDA, r2["text"], re.I):
                    c1, c2 = (kratko(r["text"]) for r in (r1, r2))
                    out.append({"text": f"В {r1['tc']} кандидат говорит о результате как о своём: «{c1}». "
                                        f"В {r2['tc']} то же число относит к отделу: «{c2}»",
                                "taymkody": f"{min(ra['tc'], rb['tc'])}, {max(ra['tc'], rb['tc'])}", "kto_nashel": "правило"})
                    break
    return out


def naiti_protivorechiya(rasshifrovka, model, ollama, potoki, maks_par=8):
    mesta_ = mesta_s_ciframi(repliki(rasshifrovka))
    out = lichnoe_protiv_komandnogo(mesta_)
    zanyato = {x["taymkody"] for x in out}
    try:
        out += [x for x in proverit_pary(rasshifrovka, model, ollama, potoki, maks_par) if x["taymkody"] not in zanyato]
    except OSError:
        pass  # модель недоступна — остаётся то, что нашло правило
    return out


def proverit_pary(rasshifrovka, model, ollama, potoki, maks_par=8):
    """Пары мест про одну величину -> модель отвечает про каждую пару отдельно. Узкий вопрос маленькая модель
    решает надёжнее, чем «найди все противоречия в разговоре» (там она пропускала явное и выдумывала лишнее)."""
    mesta = mesta_s_ciframi(repliki(rasshifrovka))
    tekst = lambda r, v: (f"HR: {v['text']}\n" if v else "") + f"Кандидат: {r['text']}"  # noqa: E731
    pary = []
    for i in range(len(mesta)):
        for j in range(i + 1, len(mesta)):
            a, b = mesta[i], mesta[j]
            if velichina(tekst(*a)) & velichina(tekst(*b)) - {"деньги"}:  # ожидания по деньгам считает код отдельно
                pary.append((a, b))
    from otchet import SRAZU_JSON

    out = []
    for (ra, va), (rb, vb) in pary[:maks_par]:
        user = f"Место 1 [{ra['tc']}]:\n{tekst(ra, va)}\n\nМесто 2 [{rb['tc']}]:\n{tekst(rb, vb)}"
        body = {"model": model, "stream": False, "format": SHEMA_PARA,
                "messages": [{"role": "system", "content": SYSTEM_PARA + SRAZU_JSON}, {"role": "user", "content": user}],
                "options": {"temperature": 0, "num_ctx": 4096, "num_thread": potoki, "num_predict": 400}}
        req = urllib.request.Request(ollama, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            try:  # ответ на пару — около 100 токенов; 4B иногда зацикливается и упирается в окно (замер 19.10, RTX 4090)
                x = json.loads(json.load(r)["message"]["content"])
            except ValueError:
                continue  # одна сорванная пара не должна ронять всё заключение
        if not isinstance(x, dict):
            continue
        if x.get("odno_i_to_zhe") and x.get("protivorechie") and not re.search(r"нет противоречи|не противоречит|согласуется", x.get("text", ""), re.I):
            out.append({"text": x["text"].strip(), "taymkody": f"{ra['tc']}, {rb['tc']}"})
    return out


# ---------- главное требование руководителя: узкий проход ----------

SHEMA_GLAVNOE = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ["подтверждает", "риск", "не обсуждали"]},
    "citata": {"type": "string", "maxLength": 200}, "poyasnenie": {"type": "string", "maxLength": 250}},
    "required": ["status", "citata", "poyasnenie"]}

SYSTEM_GLAVNOE = """Тебе дают главное требование руководителя к новому сотруднику и ответы кандидата на собеседовании.
Найди место, где кандидат говорит о том, сможет ли он выполнить именно это требование.
status: «риск» — кандидат сам говорит то, что мешает выполнить требование (не сразу, не умеет, нужно время);
«подтверждает» — кандидат прямо говорит, что делал это или сделает; «не обсуждали» — об этом нет ни слова.
citata — дословная фраза кандидата из этого места (скопируй точно), пусто если «не обсуждали».
poyasnenie — одно короткое предложение: что сказал кандидат и как это соотносится с требованием. По-русски.
О кандидате пиши «кандидат», без «он» и «она»."""


def glavnoe_trebovanie(profil):
    m = re.search(r"^## Что важно руководителю\s*\n(.*?)(?=^## |\Z)", profil, re.M | re.S)
    return m.group(1).strip() if m and m.group(1).strip() else None


def proverit_glavnoe(rasshifrovka, profil, model, ollama, potoki):
    """Ответ кандидата на главное требование руководителя. У Ольги «первый месяц уйдёт на знакомство» при требовании
    «с первого месяца сам вести 10–15 поставщиков» — общий проход это пропустил. Цитату сверяет код."""
    treb = glavnoe_trebovanie(profil)
    reps = repliki(rasshifrovka)
    if not treb or not reps:
        return None
    from otchet import SRAZU_JSON, okno

    tekst = "\n".join(f"[{r['tc']}] {'Кандидат' if kandidat_li(r['kto']) else 'HR'}: {r['text']}" for r in reps)
    user = f"# ТРЕБОВАНИЕ РУКОВОДИТЕЛЯ\n{treb}\n\n# СОБЕСЕДОВАНИЕ\n{tekst}"
    body = {"model": model, "stream": False, "format": SHEMA_GLAVNOE,
            "messages": [{"role": "system", "content": SYSTEM_GLAVNOE + SRAZU_JSON}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "num_ctx": okno(SYSTEM_GLAVNOE, user, otvet=1024), "num_thread": potoki,
                        "num_predict": 600}}
    req = urllib.request.Request(ollama, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        x = json.loads(json.load(r)["message"]["content"])
    from .yazyk import stroka

    x["trebovanie"], x["poyasnenie"] = treb, dorezat(stroka(x.get("poyasnenie", "")))
    if x["status"] != "не обсуждали":
        tc = gde_skazano(x.get("citata"), reps)
        if not tc:  # модель не смогла показать место — не верим статусу
            return {"trebovanie": treb, "status": "не обсуждали", "citata": "", "poyasnenie": "Помощник не нашёл в разговоре прямого ответа. Стоит спросить на следующем этапе."}
        x["taymkod"], x["citata"] = tc, doslovno(x["citata"], next(r["text"] for r in reps if r["tc"] == tc))
    return x


# ---------- доводка ----------

def gde_skazano(citata, reps, tolko_kandidat=True):
    """Таймкод реплики, где на самом деле есть эта цитата, или None."""
    for r in reps:
        if (not tolko_kandidat or kandidat_li(r["kto"])) and est_v_tekste(citata, r["text"]):
            return r["tc"]
    return None


def doslovno(citata, replika):
    """Цитата ровно так, как в расшифровке: модель может «поправить» слово («в том чём» вместо «в том числе»)."""
    import difflib

    a, b = replika.lower().replace("ё", "е"), citata.lower().replace("ё", "е")
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    nachalo = max(0, m.a - m.b)
    konec = min(len(replika), nachalo + len(citata))
    while nachalo > 0 and replika[nachalo - 1] not in " .,;:!?«»":  # по границам слов
        nachalo -= 1
    while konec < len(replika) and replika[konec] not in " .,;:!?«»":
        konec += 1
    return replika[nachalo:konec].strip(" ,;:")


def dorezat(t):
    """Текст, обрезанный ограничением длины посреди слова, заканчиваем на последнем целом предложении."""
    t = (t or "").strip()
    if not t or t[-1] in ".!?»)…":
        return t
    i = max(t.rfind(". "), t.rfind("! "), t.rfind("? "))
    return t[:i + 1] if i > len(t) * 0.4 else t.rsplit(" ", 1)[0].rstrip(",;:—–- ") + "…"


SINONIMY = [(r"^(ушл|уйт|уход|ушел|увол)", "уход"), (r"^(прошл|послед|предыд|бывш)", "прошл"),
             (r"^(работ|должн|мест|компан)", "место"), (r"^(поставщ|хозяйс|фермер)", "поставщ")]
STOP = {"почему", "какие", "какой", "какая", "сколько", "расскажите", "приведите", "пример", "можете", "будете"}


def slova(t):
    """Основы слов с приведением синонимов: «ушли с прошлого места» = «уйти с последнего места»."""
    out = set()
    for w in norm(t).split():
        if len(w) <= 3:
            continue
        for rx, na in SINONIMY:
            if re.match(rx, w):
                w = na
                break
        else:
            w = w[:5]
        out.add(w)
    return out - {s[:5] for s in STOP} | ({"почем"} if "почему" in norm(t) else set())


def uzhe_bylo(vopros, reps):
    """Такой вопрос уже звучал в разговоре: его задала HR или это вопрос самого кандидата к HR."""
    v = slova(vopros)
    if not v:
        return False
    for r in reps:
        for chast in re.split(r"(?<=\?)", r["text"]):
            if "?" not in chast:
                continue
            c = slova(chast)
            if c and len(v & c) / min(len(v), len(c)) >= 0.6:
                return True
    return False


def dovesti(o, profil, rasshifrovka, krasnye_flagi_profilya=()):
    reps = repliki(rasshifrovka)
    if not reps:
        return o
    # 1. цитаты и таймкоды — из расшифровки
    po_tc = {r["tc"]: r["text"] for r in reps}
    for x in o.get("kompetencii", []) + o.get("proverka_faktov", []):
        tc = gde_skazano(x.get("citata"), reps) if x.get("citata") else None
        x["citata_proverena"] = tc is not None
        if tc:
            x["taymkod"], x["citata"] = tc, doslovno(x["citata"], po_tc[tc])
    for f in o.get("proverka_faktov", []):
        for pole in ("poyasnenie", "v_istochnike"):
            f[pole] = dorezat(f.get(pole))
    for k in o.get("kompetencii", []):
        k["pochemu"] = dorezat(k.get("pochemu"))
    if o.get("glavnoe"):
        o["glavnoe"]["poyasnenie"] = dorezat(o["glavnoe"].get("poyasnenie"))
    # 2. ошибка в норме снижает оценку компетенции в этом месте и снимает зелёный флаг там же
    oshibki = {f["taymkod"] for f in o.get("proverka_faktov", []) if f.get("verdikt") == "неверно" and f.get("citata_proverena")}
    for k in o.get("kompetencii", []):
        if k.get("taymkod") in oshibki and k.get("ocenka") in LESENKA_OCENOK[1:] and "ocenka_modeli" not in k:
            k["ocenka_modeli"] = k["ocenka"]
            k["ocenka"] = LESENKA_OCENOK[LESENKA_OCENOK.index(k["ocenka"]) - 1]
            k["pochemu"] = (k.get("pochemu", "").rstrip(". ") + ". Оценка снижена: в этом месте ошибка в норме, см. проверку фактов.").lstrip(". ")
    o["zelenye_flagi"] = [z for z in o.get("zelenye_flagi", []) if z.get("taymkod") not in oshibki
                          and not re.search(r"противореч|согласу|флаг|вилк|ожидани", z.get("text", ""), re.I)]
    # служебные «флаг не срабатывает» и деньги (у денег свой блок) — не зелёный флаг
    if not o["zelenye_flagi"]:  # модель не дала годных зелёных флагов — берём её же сильные оценки
        o["zelenye_flagi"] = [{"text": f"{k['nazvanie']}: {k.get('pochemu', '').rstrip('.')}", "taymkod": k.get("taymkod", ""),
                               "iz_ocenok": True} for k in o.get("kompetencii", []) if k.get("ocenka") == "сильно"][:5]
    # 3. противоречие — это два места разговора
    o["protivorechiya"] = [x for x in o.get("protivorechiya", []) if len(set(re.findall(r"\d+:\d\d", x.get("taymkody", "")))) >= 2]
    # 4а. красный флаг должен сходиться с оценками самой модели. 19.10 у Ольги модель поставила все три флага профиля:
    # «не знает ФГИС» там, где сама оценила ФГИС «сильно», «цифры противоречат» без единого противоречия.
    po_mestu = {k.get("taymkod"): k for k in o.get("kompetencii", [])}
    ostavit, snyato = [], []
    for f in o.get("krasnye_flagi", []):
        tcs = re.findall(r"\d+:\d\d", f.get("taymkod", ""))
        k = next((po_mestu[t] for t in tcs if t in po_mestu), None)
        if not k:  # флаг без места разговора — ищем компетенцию по словам
            k = next((x for x in o.get("kompetencii", []) if len(slova(x["nazvanie"]) & slova(f.get("pravilo", ""))) >= 1), None)
        if re.search(r"противореч", f.get("pravilo", ""), re.I) and not o["protivorechiya"]:
            snyato.append(f)
        elif k and k.get("ocenka") in ("сильно", "достаточно") and not re.search(r"вилк|ожидани|противореч", f.get("pravilo", ""), re.I):
            snyato.append(f)
        else:
            ostavit.append(f)
    o["krasnye_flagi"] = ostavit
    o["flagi_snyaty"] = o.get("flagi_snyaty", []) + [
        {**f, "pochemu": "не сходится с оценкой компетенции в этом месте" if not re.search(r"противореч", f.get("pravilo", ""), re.I)
         else "противоречий в цифрах не найдено"} for f in snyato]
    # 4. флаг «цифры противоречат» из профиля ставит код, если противоречие найдено
    flag = next((f for f in krasnye_flagi_profilya if re.search(r"противореч", f, re.I)), None)
    if flag and o["protivorechiya"] and not any(f.get("pravilo") == flag for f in o.get("krasnye_flagi", [])):
        x = o["protivorechiya"][0]
        o.setdefault("krasnye_flagi", []).append({"pravilo": flag.rstrip("."), "fakt": x["text"],
                                                  "taymkod": re.findall(r"\d+:\d\d", x["taymkody"])[-1]})
    # 5. вопросы на следующий этап — новые, а не уже звучавшие
    o["voprosy_dalshe"] = [q for q in o.get("voprosy_dalshe", []) if not uzhe_bylo(q, reps)]
    return o
