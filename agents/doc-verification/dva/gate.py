"""Агент «Светофор полноты»: можно ли принимать решение по комплекту документов.

КРАСНЫЙ — хотя бы один документ не прочитан: решение не принимаем и ничего не обещаем.
ЖЁЛТЫЙ  — всё открылось, но часть страниц без текста: дочитать глазами перед решением.
ЗЕЛЁНЫЙ — каждый документ прочитан целиком.

Вывод делается по тому, чего НЕ удалось прочитать, а не по тому, что удалось.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .extract import Document, read

SUPPORTED = {".docx", ".pdf", ".txt", ".md"}


@dataclass
class Verdict:
    light: str  # "RED" | "YELLOW" | "GREEN"
    documents: list[Document]

    @property
    def problems(self) -> list[Document]:
        return [d for d in self.documents if d.status != "ok"]

    def report(self) -> str:
        label = {"RED": "🔴 КРАСНЫЙ", "YELLOW": "🟡 ЖЁЛТЫЙ", "GREEN": "🟢 ЗЕЛЁНЫЙ"}[self.light]
        lines = [f"{label}: документов {len(self.documents)}, проблемных {len(self.problems)}"]
        for d in self.documents:
            mark = {"ok": "  прочитан ", "partial": "  ЧАСТИЧНО ", "unread": "  НЕ ПРОЧИТАН"}[d.status]
            lines.append(f"{mark} {d.name}" + (f" — {'; '.join(d.reasons)}" if d.reasons else ""))
        if self.light == "RED":
            lines.append("Решение принимать нельзя: комплект неполный.")
        elif self.light == "YELLOW":
            lines.append("Перед решением дочитайте отмеченные страницы глазами.")
        return "\n".join(lines)


def check(folder: str | Path) -> Verdict:
    """Проверить все файлы папки. Неподдерживаемый формат — тоже проблема, а не повод пропустить файл."""
    root = Path(folder)
    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith("."))
    docs = [read(p) for p in files]
    if not docs:
        return Verdict("RED", [Document(root, "unread", reasons=["в папке нет ни одного документа"])])
    if any(d.status == "unread" for d in docs):
        light = "RED"
    elif any(d.status == "partial" for d in docs):
        light = "YELLOW"
    else:
        light = "GREEN"
    return Verdict(light, docs)
