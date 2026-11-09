"""Командная строка.

    python -m usn examples/vypiska-demo.csv                     отчёт по выписке
    python -m usn a.csv b.csv --moy-inn 000000000000            несколько выгрузок, дубли снимаются
    python -m usn storozh --god 2026 --test                     что сторож отправил бы сегодня
"""

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from . import ausn, klassifikaciya, nalog, sroki, vypiska, vznosy
from .storozh import Storozh, rub, tekst, telegram_iz_okruzheniya, v_konsol


def _data(s: str) -> date:
    return date.fromisoformat(s)


def vznosy_po_kvartalam(fiks: float, odin: float, kak: str, nachalo: date) -> list[float]:
    """Как распределить взносы к вычету. 'kvartaly': фиксированные равными частями по кварталам работы;
    'god': все в 4 квартале. 1 % за этот год добавляется в 4 квартал, только если его передали (odin > 0)."""
    k = [0.0] * 4
    if kak == "god":
        k[3] = fiks
    else:
        rab = list(range(nalog.kvartal(nachalo.month), 4))
        for i in rab:
            k[i] = fiks / len(rab)
    k[3] += odin
    return [round(x, 2) for x in k]


def otchet(args) -> int:
    ops, dubli = vypiska.prochitat(*args.faily)
    if not ops:
        print("В выписке нет операций")
        return 1
    god = args.god or Counter(o.data.year for o in ops).most_common(1)[0][0]
    ops_goda = [o for o in ops if o.data.year == god]
    resh = klassifikaciya.razobrat(ops_goda, args.moy_inn)
    nachalo = args.nachalo or date(god, 1, 1)
    segodnya = args.segodnya or date.today()

    dohody = [r for r in resh if r.vid == klassifikaciya.DOHOD and r.op.data >= nachalo]
    ne_dohod = [r for r in resh if r.vid == klassifikaciya.NE_DOHOD]
    rashody = [r for r in resh if r.vid == "расход"]
    dohod_god = round(sum(r.op.summa for r in dohody), 2)

    print(f"ВЫПИСКА · {god} год · файлов {len(args.faily)} · операций {len(ops_goda)} · снято дублей {dubli}")
    print()
    print(f"ДОХОД ПО УСН: {rub(dohod_god)} ({len(dohody)} поступлений)")
    gr = defaultdict(float)
    for r in ne_dohod:
        gr[r.prichina] += r.op.summa
    if gr:
        print("НЕ ДОХОД (в налог не идёт):")
        for p, s in sorted(gr.items(), key=lambda x: -x[1]):
            print(f"  {p:<42} {rub(s):>16}")
    print()

    fiks = vznosy.fiksirovannye(god, nachalo)
    odin = vznosy.odin_procent(dohod_god, god)
    k_dohod = nalog.razlozhit_po_kvartalam((r.op.data, r.op.summa) for r in dohody)
    k_vzn = vznosy_po_kvartalam(fiks, odin if args.odin_procent_v_etom_godu else 0.0, args.vznosy, nachalo)
    periody = nalog.po_kvartalam(k_dohod, k_vzn, god)

    print("НАЛОГ 6 % НАРАСТАЮЩИМ ИТОГОМ")
    print(f"  {'период':<11}{'доход':>16}{'налог 6 %':>14}{'вычет взносов':>16}{'доплатить':>14}")
    for p in periody:
        print(f"  {p.nazvanie:<11}{rub(p.dohod):>16}{rub(p.nalog):>14}{rub(p.vychet):>16}{rub(p.k_uplate):>14}")
    print()
    print("ВЗНОСЫ ЗА СЕБЯ")
    print(f"  фиксированные с {nachalo:%d.%m}: {rub(fiks)}")
    print(f"  1 % с дохода свыше порога: {rub(odin)}")
    print()

    # Сверка с ЕНС: сколько ушло в налоговую и сколько начислено по срокам, которые уже наступили
    summy = {f"avans_{p.nazvanie}": p.k_uplate for p in periody[:3]}
    summy |= {"fiks_vznosy": fiks, "nalog_za_god": periody[3].k_uplate, "odin_procent": odin}
    kal = sroki.kalendar(god, summy)
    uplacheno = round(sum(r.op.summa for r in rashody if r.prichina == "налоги и взносы (ЕНС)"), 2)
    nastupilo = round(sum(s.summa or 0 for s in kal if s.data <= segodnya), 2)
    print(f"ЕНС НА {segodnya:%d.%m.%Y}")
    print(f"  уплачено из выписки:         {rub(uplacheno):>16}")
    print(f"  начислено по наступившим срокам: {rub(nastupilo):>12}")
    raznica = round(uplacheno - nastupilo, 2)
    if raznica > 0:
        sled = next((s for s in kal if s.data > segodnya and s.summa), None)
        kuda = f"\n  Ближайшее начисление: {sled.chto.lower()} {sled.data:%d.%m.%Y}." if sled else ""
        print(f"  сверх сроков: {rub(raznica)}. ЕНС спишет их в ближайшие начисления по сроку, назначение платежа не важно.{kuda}")
    elif raznica < 0:
        print(f"  НЕДОПЛАТА: {rub(-raznica)}. Пени идут с каждого дня просрочки.")
    print("  Сверьте с кабинетом налогоплательщика: выписка видит платежи, ЕНС видит начисления.")
    print()

    print("БЛИЖАЙШИЕ СРОКИ")
    for s in [s for s in kal if s.data >= segodnya][:4]:
        summa = f" · {rub(s.summa)}" if s.summa else ""
        print(f"  {s.data:%d.%m.%Y}  {s.chto}{summa}")
    print()

    u, a = ausn.usn_vsego(dohod_god, god), ausn.ausn_vsego(dohod_god, god)
    t = ausn.tochka_pereloma(god)
    luchshe = "УСН" if u <= a else "АУСН"
    print(f"УСН 6 % ИЛИ АУСН 8 % при доходе {rub(dohod_god)}")
    print(f"  УСН: налог и взносы {rub(u)} · АУСН: {rub(a)} · выгоднее {luchshe} на {rub(abs(u - a))}")
    print(f"  Точка перелома: {rub(t)} в год. Ниже АУСН дешевле, выше УСН.")
    return 0


def storozh(args) -> int:
    god = args.god or date.today().year
    kal = sroki.kalendar(god)
    try:  # сроки за прошлый год (декларация, налог, 1 %) приходятся на этот
        kal += sroki.kalendar(god - 1)
    except KeyError:
        pass
    poslat = v_konsol if args.test else (telegram_iz_okruzheniya() or v_konsol)
    st = Storozh(kal, Path(args.zhurnal), poslat)
    segodnya = args.segodnya or date.today()
    if args.test:
        for s, ost in st.segodnya_nado(segodnya):
            v_konsol(tekst(s, ost))
        return 0
    print(f"Отправлено напоминаний: {st.progon(segodnya)}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["storozh"]:
        p = argparse.ArgumentParser(prog="python -m usn storozh", description="Напоминания о сроках")
        p.add_argument("--god", type=int)
        p.add_argument("--zhurnal", default="otpravleno.json")
        p.add_argument("--segodnya", type=_data)
        p.add_argument("--test", action="store_true", help="показать, что ушло бы сегодня, без отправки")
        return storozh(p.parse_args(argv[1:]))
    p = argparse.ArgumentParser(prog="python -m usn", description="Отчёт ИП на УСН 6 % по CSV-выписке интернет-банка")
    p.add_argument("faily", nargs="+", help="одна или несколько CSV-выгрузок, могут пересекаться")
    p.add_argument("--moy-inn", default="", help="свой ИНН: поступления с него не доход")
    p.add_argument("--god", type=int)
    p.add_argument("--nachalo", type=_data, help="дата начала УСН в этом году (регистрация или переход), ГГГГ-ММ-ДД")
    p.add_argument("--vznosy", choices=["kvartaly", "god"], default="kvartaly",
                   help="фиксированные взносы к вычету: равными частями по кварталам или все в 4 квартале")
    p.add_argument("--odin-procent-v-etom-godu", action="store_true",
                   help="учесть 1 %% за этот год в вычете 4 квартала")
    p.add_argument("--segodnya", type=_data, help="дата сверки ЕНС, по умолчанию сегодня")
    return otchet(p.parse_args(argv))
