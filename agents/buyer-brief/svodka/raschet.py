"""Деньги и проценты закупщика. Только арифметика: никаких сетевых вызовов и моделей.

Те же формулы повторяет калькулятор на странице (kalkulyator.js). Совпадение проверяет тест
на общих примерах из examples/sdelki.json.
"""

NDS_ZERNO = 10  # ставка НДС на зерно, %


def bez_nds(cena, nds=NDS_ZERNO):
    """Цена без НДС из цены с НДС."""
    return cena / (1 + nds / 100)


def izm_proc(cena, izm):
    """Изменение за неделю в процентах: цена сейчас и прирост в рублях."""
    return 100 * izm / (cena - izm)


def stoimost_deneg(summa, stavka_proc, dney):
    """Сколько стоят деньги, замороженные на dney дней под stavka_proc % годовых."""
    return summa * stavka_proc / 100 * dney / 365


def marzha_partii(cena_s_nds, partiya_t, marzha_proc, nds=NDS_ZERNO):
    """Маржа партии в рублях при отраслевой марже в процентах от выручки без НДС."""
    return bez_nds(cena_s_nds, nds) * partiya_t * marzha_proc / 100


def sdelka(obem_t, zakupka_t, prodazha_t, logistika_t, predoplata_proc, dney, stavka_proc):
    """Калькулятор сделки. Цены за тонну без НДС.

    Возвращает выручку, маржу, цену в ноль и стоимость денег под предоплату.
    """
    vyruchka = prodazha_t * obem_t
    zakupka = zakupka_t * obem_t
    logist = logistika_t * obem_t
    dengi = stoimost_deneg(zakupka * predoplata_proc / 100, stavka_proc, dney)
    marzha = vyruchka - zakupka - logist - dengi
    do_deneg = vyruchka - zakupka - logist
    return {
        "vyruchka": vyruchka,
        "dengi": dengi,
        "do_deneg": do_deneg,
        "marzha": marzha,
        "marzha_proc": marzha / vyruchka * 100 if vyruchka else 0,
        "dolya_deneg_proc": dengi / do_deneg * 100 if do_deneg > 0 else 0,
        "cena_v_nol": (zakupka + logist + dengi) / obem_t if obem_t else 0,
        "za_10_rub": 10 * obem_t,
        "minus_10_dney": stoimost_deneg(zakupka * predoplata_proc / 100, stavka_proc, 10),
    }


def rub(x, znak=False):
    """12345.6 -> «12 346», со знаком «+12 346» / «−12 346»."""
    s = f"{abs(x):,.0f}".replace(",", " ")
    if znak:
        return ("+" if x > 0 else "−" if x < 0 else "") + s
    return ("−" if x < 0 else "") + s


def proc(x):
    """2.94 -> «+2,9 %»."""
    return ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):.1f}".replace(".", ",") + " %"
