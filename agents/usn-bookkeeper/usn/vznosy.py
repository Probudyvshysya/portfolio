"""Страховые взносы ИП за себя: фиксированная часть и 1 % с дохода свыше порога (ст. 430 НК РФ)."""

import calendar
from datetime import date

from .stavki import na_god


def fiksirovannye(god: int, nachalo: date | None = None, konec: date | None = None) -> float:
    """Фиксированные взносы за период внутри года.

    Если ИП работал не весь год (регистрация, переход с другого режима, закрытие), взнос считается
    по полным месяцам, а за неполный месяц по календарным дням (п. 3 ст. 430 НК РФ).
    """
    fiks = na_god(god)["fiks_vznosy"]
    nachalo = nachalo or date(god, 1, 1)
    konec = konec or date(god, 12, 31)
    if nachalo.year != god or konec.year != god or konec < nachalo:
        raise ValueError("Период должен лежать внутри одного года и не быть пустым")
    v_mesyac = fiks / 12
    itog = 0.0
    for m in range(nachalo.month, konec.month + 1):
        dney = calendar.monthrange(god, m)[1]
        s = nachalo.day if m == nachalo.month else 1
        e = konec.day if m == konec.month else dney
        itog += v_mesyac * (e - s + 1) / dney
    return round(itog, 2)


def odin_procent(dohod: float, god: int) -> float:
    """1 % с дохода свыше порога, но не больше потолка на этот год."""
    s = na_god(god)
    sverh = max(0.0, dohod - s["porog_1_procenta"])
    return round(min(sverh * s["stavka_1_procenta"], s["maks_1_procenta"]), 2)


def vsego(dohod: float, god: int, nachalo: date | None = None, konec: date | None = None) -> float:
    return round(fiksirovannye(god, nachalo, konec) + odin_procent(dohod, god), 2)
