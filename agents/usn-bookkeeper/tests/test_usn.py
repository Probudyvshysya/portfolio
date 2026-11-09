"""Каждый тест проверяет одно правило учёта. Данные выдуманы."""

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from usn import ausn, klassifikaciya, nalog, sroki, vypiska, vznosy
from usn.cli import main, vznosy_po_kvartalam
from usn.storozh import Storozh, dney
from usn.vypiska import Operaciya

PRIMERY = Path(__file__).resolve().parent.parent / "examples"
SHAPKA = ["Дата проведения", "Номер счёта", "Номер платежа", "Сумма в валюте счёта",
          "Тип операции (пополнение/списание)", "Наименование контрагента", "ИНН контрагента",
          "Категория операции", "Назначение платежа"]


def csv_fayl(put: Path, stroki):
    with open(put, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(SHAPKA)
        w.writerows(stroki)
    return put


def op(naz="Оплата по счёту № 1", summa=1000.0, prihod=True, inn="0000000001", kat="Пополнение"):
    return Operaciya(date(2026, 3, 1), "1", "1", summa, prihod, "ООО «Пример»", inn, naz, kat)


# ---------- выписка ----------

def test_dubli_iz_peresekayushchihsya_vygruzok_snimayutsya(tmp_path):
    a = ["10.03.2026", "40802", "7", "100 000,00", "Кредит", "ООО «Пример»", "0000000001", "Пополнение", "Оплата"]
    b = ["11.03.2026", "40802", "8", "50 000,00", "Кредит", "ООО «Пример»", "0000000001", "Пополнение", "Оплата"]
    f1 = csv_fayl(tmp_path / "1.csv", [a, b])
    f2 = csv_fayl(tmp_path / "2.csv", [b])
    ops, dubli = vypiska.prochitat(f1, f2)
    assert len(ops) == 2 and dubli == 1
    assert sum(o.summa for o in ops) == 150_000


def test_odinakovaya_summa_v_odin_den_s_raznymi_nomerami_ne_dubl(tmp_path):
    a = ["10.03.2026", "40802", "7", "5000,00", "Кредит", "ООО «Пример»", "0000000001", "Пополнение", "Оплата"]
    b = ["10.03.2026", "40802", "9", "5000,00", "Кредит", "ООО «Пример»", "0000000001", "Пополнение", "Оплата"]
    ops, dubli = vypiska.prochitat(csv_fayl(tmp_path / "1.csv", [a, b]))
    assert len(ops) == 2 and dubli == 0


def test_chislo_s_probelami_i_zapyatoy():
    assert vypiska.chislo("1 234 567,89") == 1234567.89
    assert vypiska.chislo("12\xa0000,5") == 12000.5


def test_nepolnaya_vygruzka_ostanavlivaet_razbor(tmp_path):
    put = tmp_path / "plohaya.csv"
    put.write_text("Дата;Сумма\n01.01.2026;5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="нет колонок"):
        vypiska.prochitat(put)


def test_neponyatnyy_tip_operacii_ne_propuskaetsya_molcha(tmp_path):
    s = ["10.03.2026", "40802", "7", "100,00", "Возврат", "ООО «Пример»", "", "", "Оплата"]
    with pytest.raises(ValueError, match="Непонятный тип"):
        vypiska.prochitat(csv_fayl(tmp_path / "1.csv", [s]))


# ---------- доход или нет ----------

def test_perevod_sebe_ne_dohod_po_inn():
    r = klassifikaciya.klassificirovat(op("Пополнение", inn="000000000000"), moy_inn="000000000000")
    assert r.vid == klassifikaciya.NE_DOHOD and "собственных" in r.prichina


def test_perevod_sebe_ne_dohod_po_naznacheniyu():
    r = klassifikaciya.klassificirovat(op("Перевод собственных средств", inn=""))
    assert r.vid == klassifikaciya.NE_DOHOD


@pytest.mark.parametrize("naz,kat,prichina", [
    ("Выдача кредита по договору овердрафта", "Пополнение", "кредит или заём"),
    ("Зачисление", "Получение кредита", "кредит или заём"),
    ("Возврат обеспечения заявки на участие", "Пополнение", "возврат обеспечения заявки"),
    ("Возмещение комиссии за обслуживание", "Пополнение", "возврат комиссии банка"),
])
def test_ne_dohod_s_prichinoy(naz, kat, prichina):
    r = klassifikaciya.klassificirovat(op(naz, kat=kat))
    assert (r.vid, r.prichina) == (klassifikaciya.NE_DOHOD, prichina)


def test_oplata_zakazchika_dohod():
    r = klassifikaciya.klassificirovat(op("Оплата по договору № 3 за автоматизацию отчётов. Без НДС"))
    assert r.vid == klassifikaciya.DOHOD


def test_slovo_kreditnyy_v_naznachenii_ne_delaet_oplatu_kreditom():
    r = klassifikaciya.klassificirovat(op("Оплата за настройку кредитного калькулятора на сайте"))
    assert r.vid == klassifikaciya.DOHOD


def test_platezh_v_ens_raspoznan_kak_nalog():
    r = klassifikaciya.klassificirovat(op("Единый налоговый платёж", prihod=False, kat="Прочее"))
    assert r.prichina == "налоги и взносы (ЕНС)"


# ---------- взносы ----------

def test_fiksirovannye_za_polnyy_god_iz_stavok():
    assert vznosy.fiksirovannye(2026) == 57_390.00


def test_fiksirovannye_proporcionalno_s_serediny_mesyaca():
    # с 16 марта: 9 полных месяцев + 16 из 31 дня марта
    ozhid = round(57_390 / 12 * 9 + 57_390 / 12 * 16 / 31, 2)
    assert vznosy.fiksirovannye(2026, date(2026, 3, 16)) == ozhid


def test_fiksirovannye_s_pervogo_chisla_rovno_po_mesyacam():
    assert vznosy.fiksirovannye(2026, date(2026, 7, 1)) == round(57_390 / 2, 2)


def test_odin_procent_tolko_sverh_poroga():
    assert vznosy.odin_procent(300_000, 2026) == 0
    assert vznosy.odin_procent(1_300_000, 2026) == 10_000


def test_odin_procent_ne_bolshe_potolka():
    assert vznosy.odin_procent(500_000_000, 2026) == 321_818


def test_neizvestnyy_god_ne_schitaetsya_po_chuzhim_stavkam():
    with pytest.raises(KeyError, match="Нет ставок за 2031"):
        vznosy.fiksirovannye(2031)


# ---------- налог и авансы ----------

def test_vznosy_umenshayut_nalog_do_nulya():
    p = nalog.po_kvartalam([100_000, 100_000, 100_000, 100_000], [14_347.5] * 4, 2026)
    assert all(x.k_uplate == 0 for x in p)  # 6 % от 400 000 = 24 000 меньше взносов 57 390


def test_avansy_narastayushchim_itogom_bez_dvoynoy_uplaty():
    p = nalog.po_kvartalam([355_000, 545_000, 405_000, 285_000], [14_347.5] * 4, 2026)
    assert [x.k_uplate for x in p] == [6_952.5, 18_352.5, 9_952.5, 2_752.5]
    assert round(sum(x.k_uplate for x in p), 2) == p[-1].k_uplate_vsego


def test_avans_ne_byvaet_otricatelnym_a_god_pokazyvaet_pereplatu():
    p = nalog.po_kvartalam([500_000, 0, 0, 0], [0, 0, 0, 57_390], 2026)
    assert p[0].k_uplate == 30_000
    assert p[1].k_uplate == 0 and p[2].k_uplate == 0
    assert p[3].k_uplate_vsego == 0  # налог за год не ниже нуля
    assert p[3].k_uplate == -30_000  # весь аванс стал переплатой и лежит на ЕНС


def test_vznosy_s_serediny_goda_delyatsya_po_rabochim_kvartalam():
    assert vznosy_po_kvartalam(30_000, 0, "kvartaly", date(2026, 7, 1)) == [0, 0, 15_000, 15_000]
    assert vznosy_po_kvartalam(57_390, 1_000, "god", date(2026, 1, 1)) == [0, 0, 0, 58_390]


# ---------- сроки и сторож ----------

def test_srok_v_voskresene_perenositsya_na_ponedelnik():
    assert sroki.rabochiy_den(date(2027, 4, 25)) == date(2027, 4, 26)


def test_srok_v_prazdnik_perenositsya():
    assert sroki.rabochiy_den(date(2027, 1, 1)) == date(2027, 1, 11)


def test_kalendar_goda_soderzhit_vse_sroki():
    k = sroki.kalendar(2026)
    assert len(k) == 10
    daty = {s.data for s in k}
    assert {date(2026, 4, 28), date(2026, 7, 28), date(2026, 10, 28), date(2026, 12, 28)} <= daty
    assert all(s.istochnik for s in k)


def test_storozh_napominaet_v_nuzhnye_dni_i_ne_povtoryaet(tmp_path):
    srok = sroki.Srok(date(2026, 12, 28), "Фиксированные взносы", "ст. 432 НК РФ", 57_390)
    ushlo = []
    st = Storozh([srok], tmp_path / "zh.json", lambda t: ushlo.append(t) or True)
    assert st.progon(date(2026, 12, 20)) == 0  # за 8 дней молчит
    assert st.progon(date(2026, 12, 21)) == 1  # за 7 дней пишет
    assert st.progon(date(2026, 12, 21)) == 0  # повторный запуск того же дня не дублирует
    assert "Осталось 7 дней" in ushlo[0] and "57 390,00 ₽" in ushlo[0]


def test_storozh_povtoryaet_esli_otpravka_ne_proshla(tmp_path):
    srok = sroki.Srok(date(2026, 12, 28), "Взносы", "ст. 432 НК РФ")
    st = Storozh([srok], tmp_path / "zh.json", lambda t: False)
    assert st.progon(date(2026, 12, 27)) == 0
    assert json.loads((tmp_path / "zh.json").read_text(encoding="utf-8")) == {}
    st.poslat = lambda t: True
    assert st.progon(date(2026, 12, 27)) == 1


def test_sklonenie_dney():
    assert [dney(n) for n in (1, 3, 7, 11, 14, 21)] == ["день", "дня", "дней", "дней", "дней", "день"]


# ---------- УСН или АУСН ----------

def test_tochka_pereloma_ausn():
    t = ausn.tochka_pereloma(2026)
    # аналитически: 57 390 + 1 % × (D − 300 000) = 8 % × D + 2 959 → D ≈ 734 729
    assert 734_000 < t < 735_000
    assert ausn.ausn_vsego(t - 10_000, 2026) < ausn.usn_vsego(t - 10_000, 2026)
    assert ausn.ausn_vsego(t + 10_000, 2026) > ausn.usn_vsego(t + 10_000, 2026)


def test_na_usn_pri_bolshom_dohode_vznosy_ne_dobavlyayut_nagruzku():
    assert ausn.usn_vsego(3_000_000, 2026) == 180_000  # ровно 6 %: взносы целиком ушли в вычет


# ---------- целиком ----------

def test_otchet_po_demo_vypiske(capsys):
    kod = main([str(PRIMERY / "vypiska-demo.csv"), str(PRIMERY / "vypiska-demo-sentyabr-noyabr.csv"),
                "--segodnya", "2026-11-09"])
    out = capsys.readouterr().out
    assert kod == 0
    assert "снято дублей 9" in out
    assert "ДОХОД ПО УСН: 1 590 000,00 ₽" in out
    assert "сверх сроков: 43 042,50 ₽" in out
