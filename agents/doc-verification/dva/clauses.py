"""Агент «Разметка ТЗ»: каждый нумерованный пункт задания — в одну из корзин по правилам.

Зачем: прежде чем назвать цену или пообещать срок, нужно знать, какие пункты задания делаешь ты,
какие — не твой профиль (полевые работы, лаборатория, лицензия), а что обязан передать заказчик.
Правила — в JSON: корзина → список подстрок/регулярных выражений. Порядок корзин = приоритет:
пункт уходит в первую подходящую. Пункт без совпадений — «ПРОЧЕЕ», его читает человек.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CLAUSE_START = re.compile(r"^\s*(\d+(?:\.\d+){0,4})([.)])?\s+(.+)")


@dataclass
class Clause:
    number: str
    text: str
    bucket: str = "ПРОЧЕЕ"
    rule: str = ""


def split(text: str) -> list[Clause]:
    """Пункты по нумерации «1.», «2.3», «4.1.2)». Строки без номера дописываются к текущему пункту."""
    out: list[Clause] = []
    in_table = False
    for line in text.splitlines():
        if line.lstrip().startswith("|"):  # строка таблицы Word — не пункт и не его продолжение
            in_table = True
            continue
        m = CLAUSE_START.match(line)
        # «45 дней» из ячейки таблицы — не пункт: у пункта есть точка/скобка после номера,
        # составной номер («4.1») или текст с заглавной буквы
        if m and (m.group(2) or "." in m.group(1) or m.group(3)[:1].isupper()):
            out.append(Clause(m.group(1), m.group(3).strip()))
            in_table = False
        elif out and line.strip() and not in_table:
            out[-1].text += " " + line.strip()
    return out


def load_rules(path: str | Path) -> list[tuple[str, list[re.Pattern]]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(bucket, [re.compile(p, re.IGNORECASE) for p in patterns]) for bucket, patterns in raw.items()]


def classify(clauses: list[Clause], rules: list[tuple[str, list[re.Pattern]]]) -> list[Clause]:
    for c in clauses:
        for bucket, patterns in rules:
            hit = next((p for p in patterns if p.search(c.text)), None)
            if hit:
                c.bucket, c.rule = bucket, hit.pattern
                break
    return clauses


def report(clauses: list[Clause]) -> str:
    counts: dict[str, int] = {}
    for c in clauses:
        counts[c.bucket] = counts.get(c.bucket, 0) + 1
    lines = [f"Пунктов: {len(clauses)} · " + " · ".join(f"{b}: {n}" for b, n in counts.items())]
    for c in clauses:
        lines.append(f"  [{c.bucket}] п. {c.number} {c.text[:90]}")
    return "\n".join(lines)
