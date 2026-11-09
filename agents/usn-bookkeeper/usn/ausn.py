"""УСН 6 % или АУСН 8 %: сколько ИП отдаёт за год всего (налог плюс взносы) и где режимы меняются местами."""

from .stavki import na_god
from .vznosy import vsego as vznosy_vsego


def usn_vsego(dohod: float, god: int) -> float:
    """На УСН взносы платятся всегда, но целиком вычитаются из налога. Итог: большее из двух."""
    v = vznosy_vsego(dohod, god)
    nalog = max(0.0, dohod * na_god(god)["usn_stavka"] - v)
    return round(v + nalog, 2)


def ausn_vsego(dohod: float, god: int) -> float:
    """На АУСН взносов за себя нет, налог выше; плюс фиксированный взнос на травматизм."""
    s = na_god(god)
    return round(dohod * s["ausn_stavka"] + s["ausn_travmatizm"], 2)


def tochka_pereloma(god: int, ot: float = 0.0, do: float = 10_000_000.0) -> float:
    """Доход, ниже которого АУСН дешевле. Поиск делением пополам до рубля."""
    if ausn_vsego(ot, god) >= usn_vsego(ot, god):
        return ot
    while do - ot > 1:
        sered = (ot + do) / 2
        if ausn_vsego(sered, god) < usn_vsego(sered, god):
            ot = sered
        else:
            do = sered
    return round(ot)
