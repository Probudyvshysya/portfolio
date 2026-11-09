"""Налог по УСН «Доходы» нарастающим итогом: авансы за 1 квартал, полугодие, 9 месяцев и налог за год.

ИП без работников уменьшает налог на взносы за себя без ограничения, до нуля (п. 3.1 ст. 346.21 НК РФ).
Поэтому при небольшом доходе налога к уплате нет совсем: 6 % от дохода целиком перекрываются взносами.
"""

from dataclasses import dataclass

from .stavki import na_god

PERIODY = ("1 квартал", "полугодие", "9 месяцев", "год")


@dataclass(frozen=True)
class Period:
    nazvanie: str
    dohod: float  # нарастающим итогом
    nalog: float  # ставка × доход
    vychet: float  # взносы к вычету нарастающим итогом
    k_uplate_vsego: float  # налог после вычета нарастающим итогом
    k_uplate: float  # за этот период с учётом прошлых авансов; минус в годовом итоге значит переплату


def po_kvartalam(dohody_kvartalov: list[float], vznosy_kvartalov: list[float], god: int) -> list[Period]:
    """dohody_kvartalov и vznosy_kvartalov: суммы за каждый квартал отдельно, не нарастающим итогом."""
    if len(dohody_kvartalov) != 4 or len(vznosy_kvartalov) != 4:
        raise ValueError("Нужно ровно четыре квартала")
    stavka = na_god(god)["usn_stavka"]
    out, dohod, vychet, uzhe = [], 0.0, 0.0, 0.0
    for i, nazv in enumerate(PERIODY):
        dohod += dohody_kvartalov[i]
        vychet += vznosy_kvartalov[i]
        nalog = round(dohod * stavka, 2)
        posle = round(max(0.0, nalog - vychet), 2)
        k_uplate = round(posle - uzhe, 2)
        if nazv != "год":
            k_uplate = max(0.0, k_uplate)  # аванс отрицательным не бывает, излишек остаётся на ЕНС
        out.append(Period(nazv, round(dohod, 2), nalog, round(vychet, 2), posle, k_uplate))
        uzhe += k_uplate
    return out


def kvartal(mesyac: int) -> int:
    return (mesyac - 1) // 3


def razlozhit_po_kvartalam(summy_po_datam) -> list[float]:
    """[(date, сумма), ...] -> суммы по четырём кварталам."""
    k = [0.0] * 4
    for d, s in summy_po_datam:
        k[kvartal(d.month)] += s
    return [round(x, 2) for x in k]
