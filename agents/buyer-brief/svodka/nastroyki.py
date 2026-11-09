"""Параметры компании. В примере условные; на внедрении подставляются её цифры."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Nastroyki:
    partiya_t: int = 1000  # партия для расчёта, т
    predoplata_rub: int = 10_000_000  # сумма предоплат хозяйствам
    predoplata_dney: int = 30
    marzha: tuple = (1.5, 2.0)  # маржа трейдера, %, отраслевая оценка
    nds: int = 10  # НДС на зерно, %
    nadbavka_banka: float = 5.0  # маржа банка к ключевой ставке, п.п.
    logistika_t: int = 400  # логистика и хранение в калькуляторе, ₽/т
    rajony: dict = field(default_factory=lambda: {
        "Новосибирск": (55.03, 82.92),
        "Барнаул": (53.35, 83.78),
        "Омск": (54.99, 73.37),
    })
