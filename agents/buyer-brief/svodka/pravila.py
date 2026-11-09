"""Правила отбора новостей, светофор и список дел на сегодня. Решают правила, не модель."""

import re

from .nastroyki import Nastroyki
from .raschet import izm_proc, marzha_partii, rub, stoimost_deneg, proc

SIBIR = r"Сибир|Новосибир|Алта|Омск|Кемеров|Кузбас|Красноярск|Томск|Барнаул|Хакас|Тыва|Иркутск"
CHUZHIE = r"Украин|Молдов|Латви|Грузи|Белорус|Армени|Узбекистан|Киргиз|США|Евросоюз|\bЕС\b"
KATEGORII = [
    ("Контрагенты", r"банкрот|долг|арбитраж|иск |суд |взыскан|ликвидац|задолжен", 2),
    ("Цены", r"цен[аыуе]|подорож|подешев|котировк|индекс", 2),
    ("Экспорт и логистика", r"экспорт|отгрузк|порт|вагон|ж/д|РЖД|тариф|перевалк|фрахт|логистик|элеватор|хранен", 2),
    ("Господдержка и правила", r"интервенц|пошлин|квот|СДИЗ|ФГИС|Россельхознадзор|закон|постановлен|правил", 3),
    ("Деньги", r"ставк|кредит|ЦБ|Банк России|рубл", 2),
    ("Урожай", r"намолот|урожа|уборк|сев|посев", 1),
]
PROHODNOY_BALL = 3  # с этого балла новость идёт в «Главное» и читается целиком


def ocenit(n):
    """Ставит новости балл и категорию по заголовку."""
    z = n["zag"]
    ball, kat = 0, "Прочее"
    for nazv, rx, ves in KATEGORII:
        if re.search(rx, z, re.I):
            ball += ves
            if kat == "Прочее":
                kat = nazv
    if re.search(SIBIR, z):
        ball += 3
    if re.search(r"пшениц|зерн", z, re.I):
        ball += 1
    if re.search(r"мук|рис|риса|кукуруз|со[яи]|наличие", z, re.I):
        ball -= 2
    if re.search(r"Казахстан|Китай|Монгол", z):
        ball += 1
    if re.search(CHUZHIE, z):
        ball -= 3
    if re.search(r"Котировки на зерновых биржах|Итоги российских биржевых торгов|^Обзор зернового рынка", z):
        ball -= 2  # платные или сводные материалы, сырые цифры без Сибири
    n["ball"], n["kat"] = ball, kat
    return n


def sut(telo):
    """Первые предложения статьи, не длиннее 330 знаков."""
    predl = re.split(r"(?<=[.!?])\s+", telo.replace("\n", " "))
    out = ""
    for p in predl:
        if len(out) + len(p) > 330:
            break
        out += p + " "
    return out.strip() or telo[:300]


def vliyanie(n):
    """«Что это значит для нас»: вывод по категории новости для закупщика в Сибири."""
    z, t = n["zag"], n.get("telo", "")
    if n["kat"] == "Контрагенты":
        sib = "Компания из нашего макрорегиона. " if re.search(SIBIR, z + t[:400]) else ""
        return sib + "Сверить со списком хозяйств и покупателей: нет ли её или связанных с ней фирм среди контрагентов и должников. Предоплату таким не отправлять."
    if re.search(r"интервенц", z, re.I):
        okruga = re.findall(r"(Центральн\w+|Южн\w+|Северо-Кавказск\w+|Приволжск\w+|Уральск\w+|Сибирск\w+|Дальневосточн\w+)", t)
        if okruga and not re.search(r"Сибир", t):
            return "Площадки фонда только в европейской части, в Сибири государство напрямую не покупает. Поддержка цен на Юге и в Поволжье; на сибирские цены прямого влияния нет."
        return "Государство выходит покупателем: поддержка цен. Проверить, есть ли площадки фонда в наших районах."
    if n["kat"] == "Экспорт и логистика":
        return "Давление на цены там, где зерно шло в порты: Юг и Центр. Сибирь от южных портов далеко, прямое влияние слабое, это фон рынка. Для нас важнее местный спрос, переработчики и ж/д тарифы."
    if n["kat"] == "Цены":
        return "Сверить с нашими ценами закупки в таблице ниже: успеваем ли законтрактовать до следующего роста."
    if n["kat"] == "Деньги":
        return "Влияет на стоимость денег под предоплаты: расчёт в блоке «Деньги»."
    if n["kat"] == "Господдержка и правила":
        return "Проверить, касается ли нас: регион, культура, сроки вступления."
    return ""


def rost_sibir(ceny):
    sib = ceny["klass3"]["Сибирь"]
    return izm_proc(sib["cena"], sib["izm"])


def kontragenty_sibir(novosti):
    return [n for n in novosti if n["kat"] == "Контрагенты" and re.search(SIBIR, n["zag"])]


def svetofor(ceny, cb, novosti):
    """Четыре лампы: цена закупки, стоимость денег, контрагенты, сбыт. Пороги заданы здесь."""
    p = rost_sibir(ceny)
    s = [("Цена закупки", "red" if p >= 3 else "yellow" if p >= 1 else "green",
          f"Сибирь, 3 класс {proc(p)} за неделю")]
    if cb:
        s.append(("Стоимость денег", "yellow" if cb["stavka"] >= 12 else "green",
                  f"ставка {cb['stavka']:.0f} %".replace(".", ",")))
    kontr = kontragenty_sibir(novosti)
    s.append(("Контрагенты", "red" if kontr else "green",
              f"{len(kontr)} сигн. о банкротстве в регионе" if kontr else "сигналов нет"))
    eksp = [n for n in novosti if n["kat"] == "Экспорт и логистика"
            and re.search(r"сократ|сниж|остан|стоят|минимум|огранич", n["zag"], re.I)]
    s.append(("Сбыт и экспорт", "yellow" if eksp else "green",
              "порты Юга сжаты, для Сибири фон" if eksp else "без новых ограничений"))
    return s, p


def dejstviya(ceny, cb, novosti, p, nastr: Nastroyki = Nastroyki()):
    """Что сделать сегодня: короткий список с суммами в рублях."""
    d = []
    for n in kontragenty_sibir(novosti)[:2]:
        d.append(f"Сверить контрагентов с новостью: «{n['zag']}».")
    if p >= 1:
        sib = ceny["klass3"]["Сибирь"]
        d.append(f"Цена растёт: на партии {rub(nastr.partiya_t)} т рост за неделю стоит {rub(sib['izm'] * nastr.partiya_t)} ₽. "
                 "Решить, какие партии контрактовать до следующего мониторинга.")
    if cb:
        sib_c = ceny["klass3"]["Сибирь"]["cena"]
        stavka = cb["stavka"] + nastr.nadbavka_banka
        st = stoimost_deneg(nastr.predoplata_rub, stavka, nastr.predoplata_dney)
        m_lo, m_hi = (marzha_partii(sib_c, nastr.partiya_t, m, nastr.nds) for m in nastr.marzha)
        d.append((f"Предоплаты: {rub(nastr.predoplata_rub)} ₽ на {nastr.predoplata_dney} дней при кредите около {stavka:.0f} % "
                  f"(ключевая плюс маржа банка, условно) стоят около {rub(st)} ₽: при отраслевой марже "
                  f"{nastr.marzha[0]:.1f}–{nastr.marzha[1]:.0f} % это {st / m_hi * 100:.0f}–{st / m_lo * 100:.0f} % маржи партии "
                  f"{rub(nastr.partiya_t)} т (маржа от цены без НДС). Просрочка возврата съедает маржу, а невозврат забирает "
                  "всю сумму. Поэтому без проверки контрагента предоплату не отправлять.").replace(".5–", ",5–"))
    return d
