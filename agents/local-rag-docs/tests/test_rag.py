"""Проверки без Ollama: нарезка документов, сходство векторов, сверка ответа с эталоном."""
import json
from pathlib import Path

import rag

HERE = Path(__file__).parent.parent


def test_chunk_by_sections():
    text = "# Договор\n\nШапка договора.\n\n## 1. Предмет\n\nТовар.\n\n## 2. Цена\n\n38 500 ₽/т"
    chunks = rag.chunk_markdown("01.md", text)
    assert [c.section for c in chunks] == ["Шапка", "1. Предмет", "2. Цена"]
    assert chunks[2].cite == "Договор — 2. Цена"
    assert chunks[2].text == "38 500 ₽/т"


def test_empty_sections_skipped():
    chunks = rag.chunk_markdown("x.md", "# Док\n## Пусто\n\n## Есть\nтекст")
    assert [c.section for c in chunks] == ["Есть"]


def test_all_docs_have_disclaimer_and_sections():
    chunks = rag.load_chunks()
    docs = {c.doc for c in chunks}
    assert len(docs) == 4
    for path in (HERE / "docs").glob("*.md"):
        assert "выдуман" in path.read_text(encoding="utf-8")


def test_cosine():
    assert rag.cosine([1, 0], [1, 0]) == 1
    assert rag.cosine([1, 0], [0, 1]) == 0
    assert rag.cosine([0, 0], [1, 1]) == 0


def test_score_tolerates_number_format():
    assert rag.score("скидка 1.2% от цены", ["1,2 %"]) == []
    assert rag.score("в документах этого НЕТ.", [rag.NOT_FOUND]) == []
    assert rag.score("штраф 5 %", ["10 %"]) == ["10 %"]


def test_questions_point_to_existing_docs():
    prefixes = {p.name[:2] for p in (HERE / "docs").glob("*.md")}
    for case in json.loads((HERE / "questions.json").read_text(encoding="utf-8")):
        assert set(case["docs"]) <= prefixes
        assert case["expect"]
