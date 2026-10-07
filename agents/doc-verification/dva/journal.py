"""Агент «Журнал решений и ревизор»: что предложила система, что решили люди, чем кончилось.

Без журнала цепочка «подборка → решение» обрывается, и пороги отбора ни на чём не учатся.
Журнал — append-only JSONL: решение пишется с причиной и прогнозом, позже дописывается исход.
Ревизор раз в месяц сводит расхождения по сегментам: где прогноз систематически мимо,
там порог неверен, — и предлагает правку, но не вносит её сам.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Entry:
    id: str
    segment: str
    decision: str  # "take" | "skip" | "watch"
    reason: str
    forecast: float | None = None  # прогноз числом: например, ожидаемое снижение цены, %
    day: str = field(default_factory=lambda: date.today().isoformat())
    outcome: str | None = None  # "won" | "lost" | "skipped_ok" | "skipped_wrong"
    actual: float | None = None


class Journal:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def entries(self) -> list[Entry]:
        if not self.path.exists():
            return []
        rows: dict[str, Entry] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = Entry(**json.loads(line))
                rows[e.id] = e  # последняя запись по id — актуальная (журнал только дописывается)
        return list(rows.values())

    def _append(self, e: Entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")

    def add(self, e: Entry) -> None:
        if any(x.id == e.id for x in self.entries()):
            raise ValueError(f"решение {e.id} уже записано — исход дописывается через outcome()")
        self._append(e)

    def outcome(self, entry_id: str, outcome: str, actual: float | None = None) -> Entry:
        e = next((x for x in self.entries() if x.id == entry_id), None)
        if e is None:
            raise KeyError(entry_id)
        e.outcome, e.actual = outcome, actual
        self._append(e)
        return e


def review(entries: list[Entry], bias_threshold: float = 5.0) -> str:
    """Месячная ревизия: открытые решения и систематическая ошибка прогноза по сегментам."""
    open_ = [e for e in entries if e.outcome is None]
    closed = [e for e in entries if e.outcome is not None]
    lines = [f"Решений: {len(entries)} · с исходом {len(closed)} · без исхода {len(open_)}"]
    if open_:
        lines.append("  Без исхода (итоги могли уже выйти): " + ", ".join(e.id for e in open_))
    segments = sorted({e.segment for e in closed})
    for seg in segments:
        rows = [e for e in closed if e.segment == seg and e.forecast is not None and e.actual is not None]
        if not rows:
            continue
        errors = [e.actual - e.forecast for e in rows]
        bias = statistics.mean(errors)
        mae = statistics.mean(abs(x) for x in errors)
        line = f"  {seg}: прогнозов {len(rows)}, средняя ошибка {mae:.1f}, смещение {bias:+.1f}"
        if abs(bias) >= bias_threshold and len(rows) >= 2:
            line += f" → ПРЕДЛОЖЕНИЕ: сдвинуть прогноз сегмента на {bias:+.1f} (вносит человек)"
        lines.append(line)
    wrong_skips = [e for e in closed if e.outcome == "skipped_wrong"]
    if wrong_skips:
        lines.append("  Пропущено зря: " + ", ".join(f"{e.id} ({e.reason})" for e in wrong_skips) + " → пересмотреть фильтр")
    return "\n".join(lines)
