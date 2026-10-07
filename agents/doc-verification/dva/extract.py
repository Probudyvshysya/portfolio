"""Чтение документов с честным статусом: прочитан, частично, не прочитан — и почему.

Главное правило: «текста нет» и «документ пустой» — разные вещи. Скан без текстового слоя,
обрезанный PDF и Excel, который не открылся, молча превращаются в «требований нет»,
если читатель отвечает только текстом. Поэтому каждый результат несёт статус и причину.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: Меньше этого числа значимых символов на страницу — страница считается картинкой (скан).
MIN_CHARS_PER_PAGE = 40
#: Предел распакованного размера одной части .docx — защита от zip-бомб.
MAX_PART_BYTES = 50 * 2**20  # одна часть .docx после распаковки
MAX_TOTAL_BYTES = 100 * 2**20  # все части вместе


class UnsafeDocument(Exception):
    """Файл похож на атаку на парсер (zip-бомба, XXE) — не разбираем."""


@dataclass
class Document:
    path: Path
    status: str  # "ok" | "partial" | "unread"
    text: str = ""
    pages: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name


def _docx_text(path: Path) -> str:
    """Абзацы и таблицы Word в порядке документа, плюс колонтитулы и сноски.

    Стандартные конвертеры теряют текст в таблицах и сносках — а в техзаданиях именно там
    лежат объёмы и сроки. Поэтому читаем XML сами.
    """
    parts: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = ["word/document.xml"] + sorted(
            n for n in z.namelist() if re.match(r"word/(header|footer|footnotes|endnotes)\d*\.xml$", n)
        )
        total = 0
        for name in names:
            if name not in z.namelist():
                continue
            # Размер из заголовка архива можно подделать — считаем реально распакованные байты,
            # и по каждой части, и по всем частям вместе (частей-колонтитулов может быть сколько угодно).
            data = _read_capped(z, name, min(MAX_PART_BYTES, MAX_TOTAL_BYTES - total))
            total += len(data)
            # В настоящем Word нет DTD и сущностей. Их присутствие — признак подделки
            # (XXE, «billion laughs»), такой файл не разбираем вовсе.
            if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                raise UnsafeDocument(f"{name}: объявление DTD/сущностей — файл отклонён")
            parts.extend(line for line in _lines(ET.fromstring(data)) if line.strip())
    return "\n".join(parts)


def _read_capped(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    chunks, size = [], 0
    with z.open(name) as f:
        while chunk := f.read(1 << 16):
            size += len(chunk)
            if size > limit:
                raise UnsafeDocument(f"{name}: распаковывается больше допустимого (возможна zip-бомба)")
            chunks.append(chunk)
    return b"".join(chunks)


def _para(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(f"{W}t"))


def _lines(el: ET.Element):
    """Абзац — строка; строка таблицы — «| ячейка | ячейка |», чтобы её не приняли за продолжение пункта."""
    for child in el:
        if child.tag == f"{W}tbl":
            for tr in child.iter(f"{W}tr"):
                cells = [" ".join(_para(p) for p in tc.iter(f"{W}p")).strip() for tc in tr.iter(f"{W}tc")]
                yield "| " + " | ".join(cells) + " |"
        elif child.tag == f"{W}p":
            yield _para(child)
        else:
            yield from _lines(child)


def _pdf(path: Path) -> Document:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = len(reader.pages)
    texts = [(page.extract_text() or "") for page in reader.pages]
    weak = [i + 1 for i, t in enumerate(texts) if len(re.sub(r"\s", "", t)) < MIN_CHARS_PER_PAGE]
    text = "\n".join(texts)
    if pages == 0:
        return Document(path, "unread", reasons=["PDF без страниц"])
    if len(weak) == pages:
        return Document(path, "unread", text, pages, [f"PDF без текстового слоя (скан): {pages} стр. — нужно распознавание"])
    if weak:
        shown = ", ".join(map(str, weak[:10])) + ("…" if len(weak) > 10 else "")
        return Document(path, "partial", text, pages, [f"страницы без текста (вероятно, вставленные сканы): {shown}"])
    return Document(path, "ok", text, pages)


def read(path: str | Path) -> Document:
    """Прочитать один файл. Никогда не бросает исключение: ошибка — это статус «unread» с причиной."""
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        if not p.exists():
            return Document(p, "unread", reasons=["файла нет"])
        if p.stat().st_size == 0:
            return Document(p, "unread", reasons=["пустой файл (0 байт)"])
        if suffix == ".docx":
            text = _docx_text(p)
            return Document(p, "ok" if text.strip() else "unread", text, reasons=[] if text.strip() else ["в документе нет текста"])
        if suffix == ".pdf":
            return _pdf(p)
        if suffix in (".txt", ".md"):
            text = p.read_text(encoding="utf-8-sig", errors="replace")
            return Document(p, "ok" if text.strip() else "unread", text, reasons=[] if text.strip() else ["пустой текст"])
        return Document(p, "unread", reasons=[f"формат {suffix or 'без расширения'} не поддерживается — откройте вручную"])
    except zipfile.BadZipFile:
        return Document(p, "unread", reasons=["файл повреждён или это не .docx"])
    except UnsafeDocument as e:
        return Document(p, "unread", reasons=[f"небезопасный файл: {e}"])
    except Exception as e:  # чтение не должно ронять проверку всего комплекта
        return Document(p, "unread", reasons=[f"ошибка чтения: {type(e).__name__}"])
