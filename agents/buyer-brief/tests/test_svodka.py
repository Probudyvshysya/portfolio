"""Тесты сводки закупщика. Интернет не нужен: источники подменены сохранёнными ответами."""

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from svodka import istochniki, pravila
from svodka.cli import FIKSTURY, FiksturnyZapros, sobrat
from svodka.raschet import bez_nds, izm_proc, proc, rub, sdelka, stoimost_deneg

KOREN = Path(__file__).resolve().parent.parent
PRIMERY = json.loads((KOREN / "examples" / "sdelki.json").read_text(encoding="utf-8"))["primery"]
SEGODNYA = dt.date(2026, 11, 9)


def kesh():
    return json.loads((FIKSTURY / "ceny-kesh.json").read_text(encoding="utf-8"))


def ceny_s_rostom(cena, izm):
    return {"data": "2026-11-06", "istochnik": "", "klass3": {"Сибирь": {"cena": cena, "izm": izm}}}


CB = {"stavka": 15.0}


# ---------- расчёт сделки ----------

@pytest.mark.parametrize("primer", PRIMERY, ids=[p["nazvanie"] for p in PRIMERY])
def test_sdelka_kak_v_primerah(primer):
    otvet = sdelka(**primer["vhod"])
    for k, ozhid in primer["otvet"].items():
        assert otvet[k] == pytest.approx(ozhid, abs=0.01), k


@pytest.mark.skipif(shutil.which("node") is None, reason="нет Node.js")
def test_kalkulyator_na_stranice_schitaet_kak_python():
    js = (KOREN / "svodka" / "kalkulyator.js").as_posix()
    kod = (
        f"const {{schetSdelki}} = require({json.dumps(js)});"
        "const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "console.log(JSON.stringify(P.map(p => { const v = p.vhod;"
        " return schetSdelki(v.obem_t, v.zakupka_t, v.prodazha_t, v.logistika_t, v.predoplata_proc, v.dney, v.stavka_proc); })));"
    )
    r = subprocess.run(["node", "-e", kod], input=json.dumps(PRIMERY), capture_output=True, text=True,
                       encoding="utf-8", check=True)
    for primer, js_otvet in zip(PRIMERY, json.loads(r.stdout)):
        py = sdelka(**primer["vhod"])
        assert set(js_otvet) == set(py)
        for k in py:
            assert js_otvet[k] == pytest.approx(py[k], abs=1e-6), (primer["nazvanie"], k)


def test_cena_v_nol_dayot_nulevuyu_marzhu():
    v = PRIMERY[0]["vhod"]
    nol = sdelka(**v)["cena_v_nol"]
    assert sdelka(**{**v, "prodazha_t": nol})["marzha"] == pytest.approx(0, abs=1e-6)


def test_bez_predoplaty_dengi_nichego_ne_stoyat():
    r = sdelka(obem_t=1000, zakupka_t=11000, prodazha_t=11500, logistika_t=400,
               predoplata_proc=0, dney=60, stavka_proc=25)
    assert r["dengi"] == 0 and r["minus_10_dney"] == 0 and r["dolya_deneg_proc"] == 0


def test_dolya_deneg_nol_kogda_marzhi_net_i_bez_nih():
    r = sdelka(obem_t=100, zakupka_t=11000, prodazha_t=11000, logistika_t=400,
               predoplata_proc=100, dney=30, stavka_proc=20)
    assert r["do_deneg"] < 0 and r["dolya_deneg_proc"] == 0


def test_nds_procent_i_stoimost_deneg():
    assert bez_nds(11000) == pytest.approx(10000)
    assert izm_proc(10300, 300) == pytest.approx(3.0)
    assert stoimost_deneg(10_000_000, 20, 30) == pytest.approx(164_383.56, abs=0.01)


def test_format_chisel():
    assert rub(1234567.4) == "1 234 567"
    assert rub(-5000, znak=True) == "−5 000"
    assert proc(2.94) == "+2,9 %"


# ---------- правила и светофор ----------

@pytest.mark.parametrize("izm, lampa", [(99, "green"), (100, "yellow"), (299, "yellow"), (300, "red")])
def test_svetofor_ceny_na_krayah(izm, lampa):
    # при цене 10 000 + izm рост за неделю ровно izm / 100 %
    sv, _ = pravila.svetofor(ceny_s_rostom(10_000 + izm, izm), None, [])
    assert sv[0][1] == lampa


@pytest.mark.parametrize("stavka, lampa", [(11.99, "green"), (12.0, "yellow")])
def test_svetofor_stavki_na_kraju(stavka, lampa):
    sv, _ = pravila.svetofor(ceny_s_rostom(10_000, 0), {"stavka": stavka}, [])
    assert dict((a, c) for a, c, _ in sv)["Стоимость денег"] == lampa


def test_kontragenty_krasnye_tolko_po_sibiri():
    sib = pravila.ocenit({"zag": "Арбитраж ввёл наблюдение в агрохолдинге из Омской области"})
    yug = pravila.ocenit({"zag": "Арбитраж ввёл наблюдение в агрохолдинге из Ростовской области"})
    lampa = lambda n: dict((a, c) for a, c, _ in pravila.svetofor(ceny_s_rostom(10_000, 0), None, n)[0])["Контрагенты"]
    assert sib["kat"] == "Контрагенты" and sib["ball"] > yug["ball"]
    assert lampa([sib]) == "red"
    assert lampa([yug]) == "green"


def test_chuzhie_strany_nizhe_porogovogo_balla():
    n = pravila.ocenit({"zag": "Урожай зерна в Молдове оказался ниже прогноза"})
    assert n["ball"] < pravila.PROHODNOY_BALL


def test_intervencii_v_evropeyskoy_chasti_ne_pro_nas():
    n = pravila.ocenit({"zag": "Объявлены закупочные интервенции зерна",
                        "telo": "Площадки в Центральном и Приволжском федеральных округах."})
    assert "в Сибири государство напрямую не покупает" in pravila.vliyanie(n)


def test_dejstviya_berut_summy_iz_rascheta():
    ceny = ceny_s_rostom(12_100, 350)
    dej = pravila.dejstviya(ceny, CB, [], izm_proc(12_100, 350))
    st = stoimost_deneg(10_000_000, 20, 30)
    assert any("350 000 ₽" in d for d in dej)
    assert any(rub(st) in d and "1,5–2 %" in d for d in dej)


# ---------- источники ----------

def test_razbor_kursov_cb_s_nominalom():
    na, kursy = istochniki.razobrat_kursy((FIKSTURY / "cbr-kursy-seychas.xml").read_text(encoding="utf-8"))
    assert na == "10.11.2026" and kursy["USD"] == pytest.approx(81.254)
    x = '<ValCurs Date="01.01.2027"><CharCode>CNY</CharCode><Nominal>10</Nominal><Value>114,12</Value>' \
        '<CharCode>USD</CharCode><Nominal>1</Nominal><Value>81,25</Value>' \
        '<CharCode>EUR</CharCode><Nominal>1</Nominal><Value>93,87</Value></ValCurs>'
    assert istochniki.razobrat_kursy(x)[1]["CNY"] == pytest.approx(11.412)


def test_razbor_monitoringa_cen():
    t = istochniki.tekst((FIKSTURY / "interfax-prozerno.html").read_text(encoding="utf-8"))
    r = istochniki.razobrat_prozerno(t, "u", SEGODNYA)
    assert r["data"] == "2026-11-06" and r["sleduyushchij"] == "13.11"
    assert r["klass3"]["Сибирь"] == {"cena": 12100, "izm": 350}
    assert set(r["klass3"]) == {"Сибирь", "Урал", "Поволжье", "Черноземье", "Юг"}


def test_monitoring_bez_sibiri_ne_prinimaetsya():
    t = "Москва. 6 ноября. INTERFAX - Пшеница 3 класса на юге подорожала на 300 рублей, до 9 700 рублей. 4 класса"
    assert istochniki.razobrat_prozerno(t, "u", SEGODNYA) is None


def test_ceny_iz_kesha_esli_istochnik_nedostupen():
    def lezhit(url, *a, **k):
        raise OSError("нет сети")
    oshibki = []
    ceny, obnovleno = istochniki.sobrat_ceny(lezhit, kesh(), SEGODNYA, oshibki)
    assert ceny == kesh() and not obnovleno
    assert "Интерфакс недоступен" in oshibki[0]


def test_pogoda_perehodit_na_zapasnoy_istochnik():
    met = {"properties": {"timeseries": [
        {"time": "2026-11-09T00:00:00Z", "data": {"instant": {"details": {"air_temperature": -7.0}},
                                                   "next_6_hours": {"summary": {"symbol_code": "snow"},
                                                                    "details": {"precipitation_amount": 2.5}}}},
        {"time": "2026-11-09T06:00:00Z", "data": {"instant": {"details": {"air_temperature": -3.0}}}}]}}

    def zapros(url, *a, **k):
        if "open-meteo" in url:
            raise OSError("недоступен")
        return json.dumps(met)
    oshibki = []
    p = istochniki.sobrat_pogodu(zapros, {"Омск": (54.99, 73.37)}, oshibki)
    assert p["Омск"]["ist"] == "MET Norway" and p["Омск"]["sneg"] == 2.5 and not oshibki


def test_fiksturnyy_zapros_bez_seti():
    with pytest.raises(OSError):
        FiksturnyZapros()("https://example.org/")


# ---------- страница целиком ----------

def test_offline_stranica_sobiraetsya_bez_zamechaniy():
    z = FiksturnyZapros()
    html, novye, oshibki, novosti = sobrat(z, z.segodnya, kesh(), sobrano=dt.datetime(2026, 11, 9, 7, 30))
    assert oshibki == []
    assert novye["data"] == "2026-11-06"
    assert "Что сделать сегодня" in html and "Калькулятор сделки" in html and "function schetSdelki" in html
    assert "Старая новость" not in html  # старше 7 дней
    assert "доступна только для подписчиков" not in html  # платная статья опускается вниз
    assert "Технические заметки" not in html


def test_cb_nedostupen_stranica_vsyo_ravno_est():
    z = FiksturnyZapros()

    def bez_cb(url, *a, **k):
        if "cbr.ru" in url:
            raise OSError("таймаут")
        return z(url, *a, **k)
    html, _, oshibki, _ = sobrat(bez_cb, z.segodnya, kesh())
    assert "Данные ЦБ сегодня недоступны" in html
    assert "Технические заметки сборщика" in html and "ЦБ: таймаут" in html
    assert any(o.startswith("ЦБ:") for o in oshibki)


def test_starye_ceny_pomechayutsya():
    z = FiksturnyZapros()

    def bez_interfaxa(url, *a, **k):
        if "interfax" in url:
            raise OSError("нет")
        return z(url, *a, **k)
    html, novye, _, _ = sobrat(bez_interfaxa, z.segodnya, kesh())
    assert novye is None
    assert "мониторинг от 30.10.2026 · данным 10 дн., следующий мониторинг 06.11" in html
