"""Командная строка: python -m dva <агент> …"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import clauses, gate, journal, norms, refs
from .extract import read


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dva", description="Агенты проверки документов")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gate", help="светофор полноты комплекта")
    g.add_argument("folder")

    r = sub.add_parser("refs", help="сверка ссылок на нормативы")
    r.add_argument("document")
    r.add_argument("--library", required=True)

    n = sub.add_parser("norms", help="аудит библиотеки нормативов")
    n.add_argument("--registry", required=True)
    n.add_argument("--library", required=True)

    c = sub.add_parser("clauses", help="разметка пунктов ТЗ по корзинам")
    c.add_argument("document")
    c.add_argument("--rules", required=True)

    j = sub.add_parser("review", help="ревизия журнала решений")
    j.add_argument("journal")

    a = ap.parse_args(argv)
    if a.cmd == "gate":
        v = gate.check(a.folder)
        print(v.report())
        return {"GREEN": 0, "YELLOW": 1, "RED": 2}[v.light]
    if a.cmd == "refs":
        doc = read(a.document)
        if doc.status == "unread":
            print(f"Документ не прочитан: {'; '.join(doc.reasons)}")
            return 2
        cites = refs.check(doc.text, refs.load_library(a.library))
        print(refs.report(cites))
        return 1 if any(x.status == "missing" for x in cites) else 0
    if a.cmd == "norms":
        st = norms.audit(a.registry, a.library)
        print(norms.report(st))
        return 1 if any(s.status != "ok" for s in st) else 0
    if a.cmd == "clauses":
        doc = read(a.document)
        if doc.status == "unread":
            print(f"Документ не прочитан: {'; '.join(doc.reasons)}")
            return 2
        print(clauses.report(clauses.classify(clauses.split(doc.text), clauses.load_rules(a.rules))))
        return 0
    if a.cmd == "review":
        print(journal.review(journal.Journal(a.journal).entries()))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
