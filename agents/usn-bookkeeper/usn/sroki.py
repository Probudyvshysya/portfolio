"""Налоговый календарь ИП на УСН: сроки из stavki.json с переносом на рабочий день (п. 7 ст. 6.1 НК РФ)."""

from dataclasses import dataclass
from datetime import date, timedelta

from .stavki import na_god, prazdniki


@dataclass(frozen=True)
class Srok:
    data: date
    chto: str
    istochnik: str
    summa: float | None = None


def rabochiy_den(d: date, dop_vyhodnye: set[date] | None = None) -> date:
    """Ближайший рабочий день, начиная с d: выходные и праздники из ст. 112 ТК РФ пропускаются."""
    pr = set(prazdniki())
    dop = dop_vyhodnye or set()
    while d.weekday() >= 5 or d.strftime("%m-%d") in pr or d in dop:
        d += timedelta(days=1)
    return d


def _md(god: int, md: str) -> date:
    m, d = md.split("-")
    return date(god, int(m), int(d))


def kalendar(god: int, summy: dict[str, float] | None = None) -> list[Srok]:
    """Сроки по налогу и взносам за год god (часть сроков приходится на следующий год)."""
    s = na_god(god)["sroki"]
    summy = summy or {}
    out = []
    for m, kv in ((4, "1 квартал"), (7, "полугодие"), (10, "9 месяцев")):
        out.append(Srok(rabochiy_den(date(god, m, s["uvedomlenie_den"])),
                        f"Уведомление об исчисленном авансе УСН за {kv} {god}", s["uvedomlenie_istochnik"]))
        out.append(Srok(rabochiy_den(date(god, m, s["avans_den"])), f"Аванс УСН за {kv} {god}",
                        s["avans_istochnik"], summy.get(f"avans_{kv}")))
    out.append(Srok(rabochiy_den(_md(god, s["fiks_vznosy"])), f"Фиксированные взносы за {god}",
                    s["fiks_vznosy_istochnik"], summy.get("fiks_vznosy")))
    out.append(Srok(rabochiy_den(_md(god + 1, s["deklaraciya"])), f"Декларация по УСН за {god}",
                    s["deklaraciya_istochnik"]))
    out.append(Srok(rabochiy_den(_md(god + 1, s["nalog_za_god"])), f"Налог УСН за {god}",
                    s["nalog_za_god_istochnik"], summy.get("nalog_za_god")))
    out.append(Srok(rabochiy_den(_md(god + 1, s["odin_procent"])), f"Взнос 1 % с дохода свыше порога за {god}",
                    s["odin_procent_istochnik"], summy.get("odin_procent")))
    return sorted(out, key=lambda x: x.data)
