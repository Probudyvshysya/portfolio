"""Доход по УСН или нет: решение по каждой операции с причиной.

На УСН «Доходы» налог берётся со всех поступлений, кроме тех, что доходом не являются (ст. 346.15, 251 НК РФ).
Ошибка в обе стороны стоит денег: перевод самому себе, посчитанный доходом, даёт лишние 6 %, а пропущенная
оплата заказчика даёт недоимку и пени. Поэтому у каждого поступления есть причина, и человек видит её в отчёте.
"""

import re
from dataclasses import dataclass

from .vypiska import Operaciya

DOHOD = "доход"
NE_DOHOD = "не доход"

# Порядок важен: первое совпавшее правило и есть причина.
PRAVILA_NE_DOHOD = [
    ("перевод собственных средств", r"собственных средств|между своими счетами|перевод себе|со своего счёта|со своего счета"),
    ("кредит или заём", r"овердрафт|кредит[а ]|выдача кредита|получение кредита|по договору займа|\bзайм|\bзаём"),
    ("возврат обеспечения заявки", r"возврат обеспечени|возврат денежных средств обеспечени|возврат задатка"),
    ("возврат комиссии банка", r"возмещени[ея] комисси|возврат комисси|компенсация комисси"),
    ("возврат своего ошибочного платежа", r"возврат ошибочно перечисленн|возврат излишне перечисленн"),
]

NALOG = re.compile(r"единый налоговый платеж|единый налоговый платёж|\bЕНП\b|\bЕНС\b|казначейство россии|налог по усн|страховые взносы", re.I)
KOMISSIYA = re.compile(r"комисси|обслуживани[ея] счета|обслуживани[ея] счёта|тариф", re.I)


@dataclass(frozen=True)
class Reshenie:
    op: Operaciya
    vid: str  # доход / не доход / расход
    prichina: str


def klassificirovat(op: Operaciya, moy_inn: str = "") -> Reshenie:
    tekst = f"{op.naznachenie} {op.kategoriya}".lower()
    if not op.prihod:
        return Reshenie(op, "расход", gruppa_rashoda(op))
    if moy_inn and op.inn == moy_inn:
        return Reshenie(op, NE_DOHOD, "перевод собственных средств (свой ИНН)")
    if op.kategoriya.lower() == "получение кредита":
        return Reshenie(op, NE_DOHOD, "кредит или заём")
    for prichina, rx in PRAVILA_NE_DOHOD:
        if re.search(rx, tekst, re.I):
            return Reshenie(op, NE_DOHOD, prichina)
    return Reshenie(op, DOHOD, "оплата от заказчика")


def gruppa_rashoda(op: Operaciya) -> str:
    tekst = f"{op.naznachenie} {op.kategoriya} {op.kontragent}"
    if op.kategoriya.lower() == "платежи в налоговую" or NALOG.search(tekst):
        return "налоги и взносы (ЕНС)"
    if re.search(r"собственных средств|между своими|перевод себе", tekst, re.I):
        return "вывод себе"
    if re.search(r"овердрафт|погашение кредит", tekst, re.I):
        return "кредит: погашение и проценты"
    if KOMISSIYA.search(tekst):
        return "услуги банка"
    return op.kategoriya or "прочее"


def razobrat(ops: list[Operaciya], moy_inn: str = "") -> list[Reshenie]:
    return [klassificirovat(op, moy_inn) for op in ops]
