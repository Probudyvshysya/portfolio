"""Ставки и сроки из stavki.json. В коде чисел из закона нет: они в одном файле со ссылками на нормы."""

import json
from functools import lru_cache
from pathlib import Path

FAYL = Path(__file__).with_name("stavki.json")


@lru_cache(maxsize=None)
def _vse() -> dict:
    return json.loads(FAYL.read_text(encoding="utf-8"))


def na_god(god: int) -> dict:
    """Ставки за год. Если года нет в файле, это ошибка: считать по чужому году нельзя."""
    vse = _vse()
    if str(god) not in vse:
        est = ", ".join(k for k in vse if k.isdigit())
        raise KeyError(f"Нет ставок за {god} год в stavki.json (есть: {est}). Добавьте год со ссылками на нормы.")
    return vse[str(god)]


def prazdniki() -> list[str]:
    return list(_vse()["prazdniki"]["dni"])
