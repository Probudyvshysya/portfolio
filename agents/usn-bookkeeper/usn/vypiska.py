"""Разбор CSV-выписки интернет-банка: операции из нескольких выгрузок без дублей.

Выгрузки за разные периоды пересекаются: «январь-март» и «март-июнь» содержат одни и те же мартовские
операции. Если сложить файлы как есть, доход за март посчитается дважды и налог вырастет на пустом месте.
Поэтому каждая операция получает ключ (счёт, дата, номер платежа, сумма, направление) и учитывается один раз.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

KOLONKI = {
    "data": "Дата проведения",
    "schet": "Номер счёта",
    "nomer": "Номер платежа",
    "summa": "Сумма в валюте счёта",
    "tip": "Тип операции (пополнение/списание)",
    "kontragent": "Наименование контрагента",
    "poluchatel": "Наименование получателя",
    "naznachenie": "Назначение платежа",
    "opisanie": "Описание операции",
    "inn": "ИНН контрагента",
    "kategoriya": "Категория операции",
}


@dataclass(frozen=True)
class Operaciya:
    data: date
    schet: str
    nomer: str
    summa: float
    prihod: bool  # True: деньги пришли на счёт, False: ушли
    kontragent: str
    inn: str
    naznachenie: str
    kategoriya: str

    @property
    def klyuch(self) -> tuple:
        return (self.schet, self.data, self.nomer, round(self.summa, 2), self.prihod)


def chislo(s: str) -> float:
    if not s:
        return 0.0
    return float(s.replace("\xa0", "").replace(" ", "").replace(",", "."))


def _stroka(r: dict) -> Operaciya:
    def pole(k):
        return (r.get(KOLONKI[k]) or "").strip()

    tip = pole("tip").lower()
    if tip not in ("кредит", "дебет"):
        raise ValueError(f"Непонятный тип операции «{pole('tip')}»: ждём «Кредит» или «Дебет»")
    return Operaciya(
        data=datetime.strptime(pole("data"), "%d.%m.%Y").date(),
        schet=pole("schet"),
        nomer=pole("nomer"),
        summa=abs(chislo(pole("summa"))),
        prihod=tip == "кредит",
        kontragent=pole("kontragent") or pole("poluchatel"),
        inn=pole("inn"),
        naznachenie=(pole("naznachenie") or pole("opisanie")).replace("\n", " "),
        kategoriya=pole("kategoriya"),
    )


def prochitat(*puti: str | Path) -> tuple[list[Operaciya], int]:
    """Читает выгрузки, возвращает (операции по дате без дублей, сколько дублей снято)."""
    videl: dict[tuple, Operaciya] = {}
    vsego = 0
    for put in puti:
        with open(put, encoding="utf-8-sig", newline="") as f:
            chitatel = csv.DictReader(f, delimiter=";")
            net = [v for v in ("data", "summa", "tip") if KOLONKI[v] not in (chitatel.fieldnames or [])]
            if net:
                raise ValueError(f"{put}: нет колонок {', '.join(KOLONKI[v] for v in net)}")
            for r in chitatel:
                op = _stroka(r)
                vsego += 1
                videl.setdefault(op.klyuch, op)
    ops = sorted(videl.values(), key=lambda o: (o.data, o.nomer))
    return ops, vsego - len(ops)
