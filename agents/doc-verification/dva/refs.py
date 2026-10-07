"""Агент «Сверка ссылок на нормативы»: каждая ссылка «пункт 12.6.2 ГОСТ Р 59201-2021» ведёт туда, куда сказано.

В техническом томе бывает две сотни таких ссылок. Опечатка в номере пункта — ровно то, на чём
приёмка снимает работу: формально ссылка ведёт не туда. Агент находит все ссылки и проверяет,
что указанный пункт, таблица или раздел действительно есть в тексте самого норматива.

Три исхода:
  ok            — пункт найден в тексте норматива;
  missing       — норматив есть, а такого пункта в нём нет (опечатка или чужая редакция);
  unverifiable  — текста норматива нет в библиотеке: сверить вручную, «не проверено» ≠ «верно».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Обозначения нормативов: ГОСТ Р 52289-2019, ГОСТ 32965-2014, СП 34.13330.2021, ОДМ 218.4.039-2018, СНиП 2.05.02-85
# точка конца предложения в обозначение не входит: «СП 90002.2023.» → «СП 90002.2023»
DESIG = r"(?:ГОСТ\s+Р|ГОСТ|СП|ОДМ|СНиП|СанПиН)\s+\d+(?:\.\d+)*(?:-\d{2,4})?"
KIND = r"(?P<kind>пункт[а-я]*|п\.|подпункт[а-я]*|таблиц[а-я]*|табл\.|раздел[а-я]*|приложени[а-я]*)"
CITE = re.compile(KIND + r"\s+(?P<num>[А-ЯA-Z]?\d+(?:\.\d+)*)\s+(?P<doc>" + DESIG + r")", re.IGNORECASE)


@dataclass
class Citation:
    kind: str
    number: str
    document: str
    context: str
    status: str = ""


def normalize(designation: str) -> str:
    return re.sub(r"\s+", " ", designation.strip()).upper()


def _kind(raw: str) -> str:
    raw = raw.lower()
    if raw.startswith(("табл",)):
        return "table"
    if raw.startswith("раздел"):
        return "section"
    if raw.startswith("приложени"):
        return "appendix"
    return "clause"


def find_citations(text: str) -> list[Citation]:
    out = []
    for m in CITE.finditer(text):
        # контекст — своя строка (абзац), не больше 60 знаков до ссылки и 20 после
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        a = max(line_start, m.start() - 60)
        b = min(len(text) if line_end < 0 else line_end, m.end() + 20)
        out.append(Citation(_kind(m.group("kind")), m.group("num"), normalize(m.group("doc")), text[a:b].strip()))
    return out


def clause_exists(norm_text: str, kind: str, number: str) -> bool:
    """Есть ли в тексте норматива этот пункт / таблица / раздел / приложение.

    Пункт ищем как начало строки («12.6.2 Знаки…» или «12.6.2. Знаки…») — простое вхождение
    числа даёт ложные совпадения: «12.6.2» встречается внутри «12.6.21» и в чужих ссылках.
    """
    num = re.escape(number)
    if kind == "table":
        return re.search(r"(?im)^\s*Таблица\s+" + num + r"\b", norm_text) is not None
    if kind == "appendix":
        return re.search(r"(?im)^\s*Приложение\s+" + num + r"\b", norm_text) is not None
    return re.search(r"(?m)^\s*" + num + r"\.?(?!\d)(?:\s|$)", norm_text) is not None


def load_library(folder: str | Path) -> dict[str, str]:
    """Библиотека нормативов: папка .txt, обозначение берётся из первой строки файла."""
    lib: dict[str, str] = {}
    for p in sorted(Path(folder).glob("*.txt")):
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        m = re.search(DESIG, text.splitlines()[0] if text else "", re.IGNORECASE)
        if m:
            lib[normalize(m.group(0))] = text
    return lib


def check(text: str, library: dict[str, str]) -> list[Citation]:
    cites = find_citations(text)
    for c in cites:
        norm = library.get(c.document)
        if norm is None:
            c.status = "unverifiable"
        else:
            c.status = "ok" if clause_exists(norm, c.kind, c.number) else "missing"
    return cites


def report(cites: list[Citation]) -> str:
    by = {s: [c for c in cites if c.status == s] for s in ("missing", "unverifiable", "ok")}
    lines = [f"Ссылок на нормативы: {len(cites)} · верных {len(by['ok'])} · ошибочных {len(by['missing'])} · "
             f"не проверено {len(by['unverifiable'])}"]
    for c in by["missing"]:
        lines.append(f"  ❌ {c.kind} {c.number} {c.document} — нет в тексте норматива · «…{c.context}…»")
    for doc in sorted({c.document for c in by["unverifiable"]}):
        lines.append(f"  ⚠ {doc} — текста нет в библиотеке, ссылки сверить вручную")
    return "\n".join(lines)
