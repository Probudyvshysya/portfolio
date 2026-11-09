"""Локальный поиск по документам агротрейдера: вопрос → нужные пункты → ответ со ссылками.

Всё работает внутри одного компьютера через Ollama: эмбеддинги bge-m3 (на процессоре),
ответ — qwen3:4b-instruct (на видеокарте). Документы, вопросы и ответы наружу не уходят.

    python rag.py "Какой штраф за недогруз?"
    python rag.py --eval            # прогон контрольных вопросов, отчёт в results/

Модель отвечает только по найденным фрагментам и ссылается на них [1], [2].
Если ответа во фрагментах нет — пишет «В документах этого нет».
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
DOCS = HERE / "docs"
INDEX = HERE / ".index.json"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("RAG_EMBED", "bge-m3")
LLM = os.environ.get("RAG_LLM", "qwen3:4b-instruct-2507-q4_K_M")
TOP_K = 5
NOT_FOUND = "В документах этого нет"

SYSTEM = f"""Ты помощник отдела продаж агротрейдера. Отвечай по-русски, коротко и по делу.
Используй ТОЛЬКО фрагменты документов ниже. После каждого факта ставь номер фрагмента: [1], [2].
Если спрашивают об условии (штраф, срок, цена) — назови условие из документа, даже если конкретных цифр по сделке нет.
Если для ответа нужно посчитать — посчитай и покажи расчёт одной строкой.
Если во фрагментах нет ни одного подходящего условия, ответь ровно: «{NOT_FOUND}». Не додумывай."""


@dataclass
class Chunk:
    doc: str      # имя файла
    title: str    # заголовок документа
    section: str  # заголовок пункта
    text: str

    @property
    def cite(self) -> str:
        return f"{self.title} — {self.section}"


def chunk_markdown(name: str, text: str) -> list[Chunk]:
    """Режет документ по пунктам «## …»: один пункт — один фрагмент, чтобы ссылка вела на пункт."""
    title, section, body, out = name, "Шапка", [], []

    def flush():
        content = "\n".join(body).strip()
        if content:
            out.append(Chunk(name, title, section, content))

    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            section, body = line[3:].strip(), []
        else:
            body.append(line)
    flush()
    return out


def load_chunks(docs: Path = DOCS) -> list[Chunk]:
    chunks = []
    for path in sorted(docs.glob("*.md")):
        chunks += chunk_markdown(path.name, path.read_text(encoding="utf-8"))
    return chunks


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def ollama(path: str, payload: dict) -> dict:
    req = urllib.request.Request(f"{OLLAMA}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def embed(texts: list[str]) -> list[list[float]]:
    # num_gpu 0: эмбеддинги считаются на процессоре, 4 ГБ видеопамяти целиком остаются языковой модели
    return ollama("/api/embed", {"model": EMBED_MODEL, "input": texts, "options": {"num_gpu": 0}})["embeddings"]


def chunk_input(c: Chunk) -> str:
    return f"{c.cite}\n{c.text}"


def build_index(chunks: list[Chunk]) -> list[list[float]]:
    """Векторы фрагментов с кэшем на диске: пересчитываются только изменённые пункты."""
    cache = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    if cache.get("model") != EMBED_MODEL:
        cache = {"model": EMBED_MODEL, "vectors": {}}
    keys = [hashlib.sha1(chunk_input(c).encode()).hexdigest() for c in chunks]
    missing = [(k, c) for k, c in zip(keys, chunks) if k not in cache["vectors"]]
    if missing:
        for (k, _), v in zip(missing, embed([chunk_input(c) for _, c in missing])):
            cache["vectors"][k] = v
        cache["vectors"] = {k: cache["vectors"][k] for k in keys}
        INDEX.write_text(json.dumps(cache), encoding="utf-8")
    return [cache["vectors"][k] for k in keys]


def search(question: str, chunks: list[Chunk], vectors: list[list[float]], k: int = TOP_K):
    q = embed([question])[0]
    ranked = sorted(zip(chunks, (cosine(q, v) for v in vectors)), key=lambda p: p[1], reverse=True)
    return ranked[:k]


def chat(messages: list[dict]) -> dict:
    """Запрос к модели. Если видеопамяти не хватило (её делят браузер, игры, созвоны),
    повторяем, оставляя на видеокарте меньше слоёв: медленнее, но ответ будет."""
    options = {"temperature": 0, "num_ctx": 4096}
    layers = [int(os.environ["RAG_GPU_LAYERS"])] if "RAG_GPU_LAYERS" in os.environ else [None, 20, 12, 0]
    for n in layers:
        if n is not None:
            options["num_gpu"] = n
        try:
            return ollama("/api/chat", {"model": LLM, "stream": False, "think": False,
                                        "options": options, "messages": messages})
        except urllib.error.HTTPError as e:
            if e.code != 500 or n == layers[-1]:
                raise
            print(f"  нехватка памяти, слоёв на видеокарте: {'авто' if n is None else n} → меньше", file=sys.stderr)


def ask(question: str, found: list[tuple[Chunk, float]]) -> dict:
    context = "\n\n".join(f"[{i}] {c.cite}\n{c.text}" for i, (c, _) in enumerate(found, 1))
    r = chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Фрагменты:\n\n{context}\n\nВопрос: {question}"},
    ])
    answer = re.sub(r"^.*?</think>", "", r["message"]["content"], flags=re.S).strip()
    gen_s = r.get("eval_duration", 0) / 1e9
    return {
        "answer": answer,
        "tokens": r.get("eval_count", 0),
        "tok_per_s": round(r.get("eval_count", 0) / gen_s, 1) if gen_s else 0.0,
    }


def normalize(s: str) -> str:
    """Для сверки с эталоном: «1.2 %» и «1,2%» считаются одним и тем же."""
    return re.sub(r"\s+", "", s.lower().replace("ё", "е").replace(".", ",").replace(" ", " "))


def score(answer: str, expect: list[str]) -> list[str]:
    """Какие обязательные факты НЕ попали в ответ."""
    a = normalize(answer)
    return [e for e in expect if normalize(e) not in a]


def run_one(question: str, chunks, vectors) -> dict:
    t0 = time.perf_counter()
    found = search(question, chunks, vectors)
    t1 = time.perf_counter()
    res = ask(question, found)
    t2 = time.perf_counter()
    return {**res, "found": found, "search_s": round(t1 - t0, 2), "total_s": round(t2 - t0, 1)}


def print_answer(question: str, r: dict) -> None:
    print(f"\n❓ {question}\n")
    print(r["answer"])
    print("\nФрагменты:")
    for i, (c, s) in enumerate(r["found"], 1):
        print(f"  [{i}] {s:.2f}  {c.cite}")
    print(f"\n⏱ поиск {r['search_s']} с, всего {r['total_s']} с, генерация {r['tok_per_s']} ток/с")


def run_eval(chunks, vectors) -> Path:
    cases = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    rows, ok_answers, ok_search = [], 0, 0
    for case in cases:
        r = run_one(case["q"], chunks, vectors)
        docs_found = {c.doc[:2] for c, _ in r["found"]}
        search_ok = set(case["docs"]) <= docs_found
        missing = score(r["answer"], case["expect"])
        ok_search += search_ok
        ok_answers += not missing
        print_answer(case["q"], r)
        print(f"   поиск: {'✅' if search_ok else '❌'}  ответ: {'✅' if not missing else '❌ нет ' + ', '.join(missing)}")
        rows.append((case, r, search_ok, missing))

    n = len(cases)
    times = sorted(r["total_s"] for _, r, _, _ in rows)
    out = [f"# Прогон {date.today():%d.%m.%Y}: {LLM} + {EMBED_MODEL}, top-{TOP_K}", "",
           f"Нужные документы нашлись: **{ok_search} из {n}**. Ответ содержит все обязательные факты: "
           f"**{ok_answers} из {n}**. Время ответа: медиана {times[n // 2]} с, максимум {times[-1]} с.", "",
           "| # | Вопрос | Поиск | Ответ | Время, с | Чего не хватило |", "|---|---|---|---|---|---|"]
    for i, (case, r, s_ok, miss) in enumerate(rows, 1):
        out.append(f"| {i} | {case['q']} | {'✅' if s_ok else '❌'} | {'✅' if not miss else '❌'} "
                   f"| {r['total_s']} | {', '.join(miss) or '—'} |")
    out += ["", "## Ответы модели целиком", ""]
    for i, (case, r, _, _) in enumerate(rows, 1):
        cites = "; ".join(f"[{j}] {c.cite}" for j, (c, _) in enumerate(r["found"], 1))
        out += [f"**{i}. {case['q']}**", "", "> " + r["answer"].replace("\n", "\n> "), "",
                f"<sub>Фрагменты: {cites}. Эталон: {case['why']}</sub>", ""]
    path = HERE / "results" / f"eval-{date.today():%Y-%m-%d}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"\nИтог: поиск {ok_search}/{n}, ответы {ok_answers}/{n}. Отчёт: {path}")
    return path


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question", nargs="?")
    p.add_argument("--eval", action="store_true", help="прогнать questions.json и записать отчёт")
    args = p.parse_args()
    if not args.question and not args.eval:
        p.error("задайте вопрос или --eval")

    chunks = load_chunks()
    t0 = time.perf_counter()
    vectors = build_index(chunks)
    print(f"Фрагментов: {len(chunks)} из {len({c.doc for c in chunks})} документов, индекс {time.perf_counter() - t0:.1f} с")
    if args.eval:
        run_eval(chunks, vectors)
    else:
        print_answer(args.question, run_one(args.question, chunks, vectors))


if __name__ == "__main__":
    main()
