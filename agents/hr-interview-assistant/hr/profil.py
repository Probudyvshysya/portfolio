"""Профиль должности из фактуры HR и ответов на чек-лист. Модель собирает черновик, HR правит и сохраняет."""

import json
import sys
import urllib.request
from pathlib import Path

ROOT_KOMPLEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_KOMPLEKT))
from otchet import MODEL, OLLAMA, POTOKI, SRAZU_JSON, STIL, ochistit  # noqa: E402

CHEK_LIST = [
    ("dolzhnost", "Должность, отдел, кому подчиняется"),
    ("zadachi", "Что человек будет делать: главные задачи, объёмы"),
    ("opyt", "Какой опыт обязателен: сколько лет, в чём именно"),
    ("znaniya", "Какие знания и навыки проверяем на собеседовании (и по каждому: что считаем хорошим уровнем)"),
    ("glavnoe", "Что для руководителя важнее всего"),
    ("krasnye", "С чем точно не берём (красные флаги)"),
    ("dengi", "Вилка на руки, бонусы; на сколько % выше вилки уже «дорого» (обычно 20 %)"),
    ("metriki", "Как поймём через 3 месяца, что человек справляется"),
    ("uslovia", "График, формат работы, командировки"),
]

# Только структура, без содержания: иначе модель переносит в новую вакансию чужие факты из образца
OBRAZEC = """# Профиль должности: <должность>

Отдел, кому подчиняется: <из ответов HR>
Вилка: <из ответов HR>

## Задачи
1. <задача, с объёмами, если HR их назвала>

## Компетенции (вес от 1 до 3)
| Компетенция | Вес | Что считаем хорошим уровнем |
|---|---|---|
| <навык> | <1–3> | <конкретно и проверяемо на собеседовании> |

## Красные флаги
- <из ответов HR>
- Ожидания по деньгам выше вилки больше чем на <N> %.

## Что важно руководителю
<из ответов HR>

## Как поймём через 3 месяца, что человек справляется
<из ответов HR>

## Условия работы
<график, формат, командировки>"""

SYSTEM = f"""Ты помогаешь менеджеру по персоналу оформить профиль должности.
Из её слов собери профиль СТРОГО в формате образца ниже: те же разделы, таблица компетенций с весом от 1 до 3
(3 — без этого не берём), колонка «Что считаем хорошим уровнем» — конкретно и проверяемо на собеседовании.
В разделе «Красные флаги» обязательно строка «Ожидания по деньгам выше вилки больше чем на N %» (N из её слов, иначе 20).
Обязательный опыт из её ответов — первая строка таблицы компетенций (вес 3); каждый навык из ответа про знания —
отдельная строка. Красные флаги переноси её словами, без сокращений.
Не выдумывай факты, которых она не говорила: если чего-то нет — напиши «уточнить у руководителя».
Ответ — только markdown профиля, без пояснений.

ОБРАЗЕЦ:
{OBRAZEC}

{STIL}"""


def sobrat(nazvanie, faktura, otvety, model=MODEL):
    chast = [f"Должность: {nazvanie}", f"Как HR описала своими словами:\n{faktura.strip() or '—'}", "Ответы на чек-лист:"]
    for k, vopros in CHEK_LIST:
        chast.append(f"- {vopros}: {(otvety or {}).get(k, '').strip() or '—'}")
    body = {"model": model, "stream": False,
            "messages": [{"role": "system", "content": SYSTEM + SRAZU_JSON}, {"role": "user", "content": "\n".join(chast)}],
            "options": {"temperature": 0, "num_ctx": 8192, "num_thread": POTOKI}}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        text = json.load(r)["message"]["content"].strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("markdown").strip()
    return normalizovat(ochistit(text))


ZAGOLOVKI = ["Задачи", "Компетенции (вес от 1 до 3)", "Красные флаги", "Что важно руководителю",
             "Как поймём через 3 месяца, что человек справляется", "Условия работы"]


def normalizovat(text):
    """Заголовки разделов заданы шаблоном — приводим их к точному виду (маленькая модель иногда их искажает);
    убираем хвостовые пробелы и типичные обрывы аббревиатур."""
    import difflib
    import re

    from .yazyk import stroka as po_chelovecheski

    out = []
    for stroka in text.splitlines():
        stroka = stroka.rstrip()
        if not stroka.startswith(("|", "#")):  # в таблице «—» значит пустую клетку
            stroka = po_chelovecheski(stroka) if stroka.strip() else stroka
        if stroka.startswith("## "):
            bliz = difflib.get_close_matches(stroka[3:].strip(), ZAGOLOVKI, n=1, cutoff=0.5)
            if bliz:
                stroka = "## " + bliz[0]
        stroka = re.sub(r"\bФГИ\b(?!С)", "ФГИС «Зерно»", stroka)
        out.append(stroka)
    return "\n".join(out)
