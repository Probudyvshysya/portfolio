"""Агент «Аудит библиотеки нормативов»: тот ли это документ и та ли редакция.

Реестр «файл лежит на диске» отвечает не на тот вопрос. На приёмке спросят другое:
та ли редакция и тот ли это вообще документ. Классические ошибки:
  · ПОДМЕНА — файл назван по номеру постановления, а внутри другое постановление с тем же номером;
  · УСТАРЕЛО — текст первоначальной редакции, без изменений, на которые ссылается задание;
  · НЕТ — файла нет, хотя задание на него ссылается.

Ожидания описываются в реестре (JSON): обозначение, ключевые слова названия, маркеры актуальной редакции.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .refs import load_library, normalize


@dataclass
class NormStatus:
    designation: str
    status: str  # "ok" | "substitution" | "outdated" | "absent"
    notes: list[str] = field(default_factory=list)


def audit(registry_path: str | Path, library_folder: str | Path) -> list[NormStatus]:
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    library = load_library(library_folder)
    out = []
    for item in registry:
        desig = normalize(item["designation"])
        text = library.get(desig)
        if text is None:
            out.append(NormStatus(desig, "absent", ["текста в библиотеке нет"]))
            continue
        low = text.lower()
        missing_title = [w for w in item.get("title_keywords", []) if w.lower() not in low]
        if missing_title:
            out.append(NormStatus(desig, "substitution", [f"нет слов из названия: {', '.join(missing_title)} — внутри другой документ"]))
            continue
        missing_edition = [w for w in item.get("edition_markers", []) if w.lower() not in low]
        if missing_edition:
            out.append(NormStatus(desig, "outdated", [f"нет изменений актуальной редакции: {', '.join(missing_edition)}"]))
            continue
        out.append(NormStatus(desig, "ok"))
    return out


def report(statuses: list[NormStatus]) -> str:
    icon = {"ok": "✅", "substitution": "🔴 ПОДМЕНА", "outdated": "🟠 УСТАРЕЛО", "absent": "⚪ НЕТ"}
    bad = [s for s in statuses if s.status != "ok"]
    lines = [f"Нормативов в реестре: {len(statuses)} · в порядке {len(statuses) - len(bad)} · требуют внимания {len(bad)}"]
    for s in statuses:
        lines.append(f"  {icon[s.status]} {s.designation}" + (f" — {'; '.join(s.notes)}" if s.notes else ""))
    return "\n".join(lines)
