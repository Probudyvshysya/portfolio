"""Человеческий язык в ответах модели: механическая чистка после ответа.

Маленькая модель держит правила стиля из задания не всегда — добиваем кодом то, что заменяется без риска для смысла:
тире, «данный», пустые подводки. Слова кандидата (цитаты) и выдержки из документов не трогаем — это чужой текст.
"""

import re

NE_TROGAT = {"citata", "fakt_citata", "v_istochnike", "istochnik", "text_istochnika", "taymkod", "taymkody", "zapros",
             "url", "dokument", "razdel", "horoshiy_otvet", "trebovanie"}

# «данные», «данных», «по данным» чаще значат «сведения» — их не трогаем
DANNYY = {"данный": "этот", "данная": "эта", "данное": "это", "данного": "этого", "данной": "этой", "данном": "этом",
          "данную": "эту"}
PODVODKI = re.compile(r"\b(?:Стоит|Важно|Следует|Необходимо) (?:отметить|подчеркнуть|понимать|учитывать|помнить), что\s+", re.I)
TIRE = re.compile(r"\s+[—–]\s+|\s+-\s+")


def _tire(stroka):
    """Тире между словами: в начале фразы («Риски — нет опыта») — двоеточие, «X — это Y» — «X это Y», дальше — запятая."""
    out, nachalo = [], 0
    for m in TIRE.finditer(stroka):
        do = stroka[nachalo:m.start()]
        posle = stroka[m.end():]
        fraza = re.split(r"[.!?:;]\s", stroka[:m.start()])[-1]
        if posle.startswith("это ") or re.match(r"(?:\d|не более|не менее|не ниже|не выше|около|примерно)", posle):
            zamena = " "  # «для 4 класса — не менее 18 %» -> «для 4 класса не менее 18 %»
        elif re.match(r"(?:что|как|сколько|какие|какой|какая|где|когда|почему|кто|чем)\b", posle):
            zamena = ": "  # «приведите пример — что было» -> «приведите пример: что было»
        elif len(fraza.split()) <= 3 and "," not in fraza:
            zamena = ": "
        else:
            zamena = ", "
        out += [do, zamena]
        nachalo = m.end()
    out.append(stroka[nachalo:])
    s = "".join(out)
    return re.sub(r",\s*,", ",", s)


def _dannyy(m):
    slovo = m.group(0)
    z = DANNYY[slovo.lower()]
    return z.capitalize() if slovo[0].isupper() else z


VY_GLAGOL = re.compile(r"\b([Вв]ы(?: сами| сам)?) ([а-яё]+?)(ёл|ел|ал|ял|ил|ыл|ул|ол)(ся)?\b")
OKONCHANIE = {"ёл": "ели", "ел": "ели", "ал": "али", "ял": "яли", "ил": "или", "ыл": "ыли", "ул": "ули", "ол": "оли"}


def _vy(m):
    """«вы вёл» -> «вы вели», «вы отказался» -> «вы отказались»: маленькая модель путает число после «вы»."""
    kto, osnova, ok, sya = m.group(1), m.group(2), m.group(3), m.group(4) or ""
    if osnova.endswith("ш") and ok == "ёл":  # «вы пришёл» -> «вы пришли»
        return f"{kto.replace(' сам', ' сами') if kto.endswith(' сам') else kto} {osnova}ли{'сь' if sya else ''}"
    kto = kto[:-4] + " сами" if kto.endswith(" сам") else kto
    return f"{kto} {osnova}{OKONCHANIE[ok]}{'сь' if sya else ''}"


# опечатки, которые маленькая модель повторяет; пополнять по мере находок
OPECHATKI = [(r"\bФГИ\s+и\s+С\b", "ФГИС"), (r"\bвёли\b", "вели"), (r"\b[Пп]утует\b", "путает"), (r"\bза тонн\b", "за тонну"),
             (r"\bпереговаривались с поставщиком\b", "вели переговоры с поставщиком"),
             # к кандидату на «вы»: модель сбивается на «ты» в вопросах
             (r"\bПриведи\b", "Приведите"), (r"\bРасскажи\b", "Расскажите"), (r"\bОпиши\b", "Опишите"),
             (r"\bНазови\b", "Назовите"), (r"\bОбъясни\b", "Объясните"), (r"\bПокажи\b", "Покажите"),
             (r"\bу тебя\b", "у вас"), (r"\bтебе\b", "вам"), (r"\bтвоей\b", "вашей"), (r"\bтвоих\b", "ваших"),
             (r"\b([Уу]) (?:него|неё)\b", r"\1 кандидата"),  # пол модель угадывает плохо («у него» про Марину)
             (r"\b(что|так как|потому что|поэтому|и|но|хотя) (?:он|она) ", r"\1 кандидат "),
             (r"\bтвой\b", "ваш"), (r"\bтвоя\b", "ваша"), (r"\bТы\b", "Вы"), (r"\bты\b", "вы")]


def stroka(s):
    if not isinstance(s, str) or not s:
        return s
    for a, b in OPECHATKI:
        s = re.sub(a, b, s)
    s = _tire(s)
    s = VY_GLAGOL.sub(_vy, s)
    s = re.sub(r"\b[Дд]анн(?:ый|ая|ое|ого|ой|ом|ую)\b", _dannyy, s)
    # после снятой подводки фраза начинается с маленькой буквы — поднимаем только там («тыс. т» не трогаем)
    s = PODVODKI.sub(lambda m: "\0" if m.start() == 0 or s[m.start() - 2:m.start()].strip() in ".!?" else "", s)
    s = re.sub(r"\0(\w)", lambda m: m.group(1).upper(), s).replace("\0", "")
    return re.sub(r" {2,}", " ", s).strip()


TY_GLAGOL = re.compile(r"\b(?!лишь\b)([А-ЯЁа-яё]{2,}?)(ешь|ёшь|ишь)(ся)?\b")


def k_vy(vopros):
    """Вопрос кандидату — на «вы»: «как вы ведёшь» -> «как вы ведёте», «что сделал» -> «что сделали».
    Только для вопросов: в остальном тексте «что сделал» — это про кандидата в третьем лице."""
    if not isinstance(vopros, str):
        return vopros
    s = stroka(vopros)
    s = TY_GLAGOL.sub(lambda m: m.group(1) + {"ешь": "ете", "ёшь": "ёте", "ишь": "ите"}[m.group(2)] + ("сь" if m.group(3) else ""), s)
    s = re.sub(r"\b(вы )?достиг\b", lambda m: (m.group(1) or "") + "достигли", s)
    s = re.sub(r"\bчто сделал\b", "что сделали", s)
    s = re.sub(r"\bчем кончилось\b", "чем закончилось", s)
    return s


def po_russki(t):
    """Маленькая модель иногда отвечает по-английски. Названия вроде Excel или CRM допустимы, фраза целиком — нет."""
    lat = len(re.findall(r"[A-Za-z]", t or ""))
    kir = len(re.findall(r"[А-Яа-яЁё]", t or ""))
    return lat <= 0.3 * (lat + kir)


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[«»\"'“”.,;:!?()…—–-]", " ", (t or "").lower().replace("ё", "е"))).strip()


def est_v_tekste(citata, tekst, porog=0.8):
    """Цитата действительно есть в тексте (резюме, расшифровке): дословно или почти — модель может съесть
    знак, слово или обрезать конец. Ищем самый длинный общий кусок и сравниваем цитату с этим местом текста."""
    import difflib

    c, t = norm(citata), norm(tekst)
    if len(c) < 8:
        return False
    if c in t:
        return True
    m = difflib.SequenceMatcher(None, t, c, autojunk=False).find_longest_match(0, len(t), 0, len(c))
    if m.size < 6:
        return False
    nachalo = max(0, m.a - m.b - 5)
    okno = t[nachalo:nachalo + len(c) + 10]
    return difflib.SequenceMatcher(None, okno, c, autojunk=False).ratio() >= porog


VYCHITKA = """Ты корректор. Тебе дают список фраз на русском. Исправь в каждой опечатки, ошибки в окончаниях и согласовании,
обращение к человеку на «ты» замени на «вы». Не меняй смысл, термины, названия, цифры и порядок фраз.
Если в фразе ошибок нет, верни её как есть. Верни столько же фраз, в том же порядке."""


def vychitat(teksty, model=None, porog=0.8):
    """Второй проход моделью: опечатки и согласование («Путует», «за тонн»). Правку берём, только если фраза
    осталась похожей на исходную: корректор не должен переписывать смысл."""
    import difflib
    import json
    import urllib.request

    from otchet import MODEL, OLLAMA, POTOKI, SRAZU_JSON, ochistit

    if not teksty:
        return teksty
    shema = {"type": "object", "properties": {"frazy": {"type": "array", "minItems": len(teksty), "maxItems": len(teksty),
                                                          "items": {"type": "string"}}}, "required": ["frazy"]}
    spisok = "\n".join(f"{n + 1}. {t}" for n, t in enumerate(teksty))
    body = {"model": model or MODEL, "stream": False, "format": shema,
            "messages": [{"role": "system", "content": VYCHITKA + SRAZU_JSON}, {"role": "user", "content": spisok}],
            "options": {"temperature": 0, "num_ctx": 8192, "num_thread": POTOKI}}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        novye = ochistit(json.loads(json.load(r)["message"]["content"])).get("frazy", [])
    out = []
    for star, nov in zip(teksty, novye + teksty[len(novye):]):
        nov = re.sub(r"^\d+\.\s*", "", nov or "").strip()
        out.append(stroka(nov) if nov and difflib.SequenceMatcher(None, star, nov).ratio() >= porog else star)
    return out


def ochelovechit(x, klyuch=None):
    """Проходит по ответу модели (dict/list/str) и чистит строки, кроме чужих слов."""
    if klyuch in NE_TROGAT:
        return x
    if isinstance(x, str):
        return stroka(x)
    if isinstance(x, list):
        return [ochelovechit(v, klyuch) for v in x]
    if isinstance(x, dict):
        return {k: ochelovechit(v, k) for k, v in x.items()}
    return x
