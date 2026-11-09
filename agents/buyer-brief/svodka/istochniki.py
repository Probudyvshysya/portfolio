"""Сбор открытых данных: ЦБ, отраслевые новости, недельные цены, погода.

Каждая функция получает `zapros(url, kodirovka, tajmaut) -> str`. В работе это настоящий HTTP,
в тестах и в режиме --offline сохранённые ответы из examples/fixtures. Ошибка источника не роняет
сводку: она уходит в список `oshibki` и показывается в технических заметках страницы.
"""

import datetime as dt
import html
import json
import re
import ssl
import urllib.request

from . import pravila

UA = {"User-Agent": "Mozilla/5.0 (svodka-zakupshchika)"}


def zapros_http(url, kodirovka="utf-8", tajmaut=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=tajmaut, context=ssl.create_default_context()) as r:
        return r.read().decode(kodirovka, "replace")


def tekst(h):
    """HTML -> простой текст с переносами по абзацам."""
    h = re.sub(r"(?s)<(script|style).*?</\1>", "", h)
    h = re.sub(r"<br\s*/?>|</p>|</li>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", "", h))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def chislo(s):
    return float(s.replace(" ", "").replace("\xa0", "").replace(",", "."))


# ---------- ЦБ ----------
def razobrat_kursy(x):
    """XML_daily ЦБ -> дата и курсы CNY, USD, EUR за одну единицу валюты."""
    na = re.search(r'Date="([\d.]+)"', x).group(1)
    res = {}
    for kod in ("CNY", "USD", "EUR"):
        m = re.search(rf"<CharCode>{kod}</CharCode>.*?<Nominal>(\d+)</Nominal>.*?<Value>([\d,]+)</Value>", x, re.S)
        res[kod] = chislo(m.group(2)) / int(m.group(1))
    return na, res


def kursy_na(zapros, data):
    return razobrat_kursy(zapros(f"http://www.cbr.ru/scripts/XML_daily.asp?date_req={data:%d/%m/%Y}", "cp1251"))


def sobrat_cb(zapros, segodnya, oshibki):
    try:
        na, sejchas = kursy_na(zapros, segodnya + dt.timedelta(days=1))
        na_ranshe, ranshe = kursy_na(zapros, segodnya - dt.timedelta(days=6))
        k = zapros("http://www.cbr.ru/hd_base/KeyRate/")
        stavki = re.findall(r"<td>(\d\d\.\d\d\.\d{4})</td>\s*<td>([\d,]+)</td>", k)
        return {"na": na, "na_ranshe": na_ranshe, "sejchas": sejchas, "ranshe": ranshe,
                "stavka": chislo(stavki[0][1]), "stavka_na": stavki[0][0]}
    except Exception as e:
        oshibki.append(f"ЦБ: {e}")
        return None


# ---------- Новости ----------
def sobrat_novosti(zapros, segodnya, oshibki):
    try:
        h = zapros("https://www.zerno.ru/")
    except Exception as e:
        oshibki.append(f"zerno.ru: {e}")
        return []
    novosti, videl = [], set()
    for data, ssylka, zag in re.findall(r"(\d\d\.\d\d\.\d{4})\s*</[^>]+>\s*(?:<[^>]+>\s*)*<a href=\"(/node/\d+)\"[^>]*>([^<]+)</a>", h):
        d = dt.datetime.strptime(data, "%d.%m.%Y").date()
        zag = html.unescape(zag).strip()
        if ssylka in videl or (segodnya - d).days > 7:
            continue
        videl.add(ssylka)
        novosti.append({"data": d, "url": "https://www.zerno.ru" + ssylka, "zag": zag})
    for n in novosti:
        pravila.ocenit(n)
    novosti.sort(key=lambda n: (-n["ball"], -n["data"].toordinal()))
    for n in [n for n in novosti if n["ball"] >= pravila.PROHODNOY_BALL][:10]:
        try:
            h = zapros(n["url"])
            m = re.search(r'field-name-body.*?property="content:encoded">(.*?)</div></div></div>', h, re.S)
            n["telo"] = tekst(m.group(1)) if m else ""
        except Exception as e:
            n["telo"] = ""
            oshibki.append(f"статья {n['url']}: {e}")
        if "доступна только для подписчиков" in n["telo"] or not n["telo"]:
            n["ball"] -= 5
        n["sut"] = pravila.sut(n["telo"])
        n["chto_znachit"] = pravila.vliyanie(n)
    novosti.sort(key=lambda n: (-n["ball"], -n["data"].toordinal()))
    return novosti


# ---------- Цены «ПроЗерно» ----------
MESYACY = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
           "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}


def razobrat_prozerno(t, url, segodnya):
    """Текст новости о недельном мониторинге -> цены пшеницы 3 класса по регионам. Без Сибири None."""
    reg = {"Сибирь": "в Сибири", "Урал": "на Урале", "Поволжье": "в Поволжье", "Юг": "на юге", "Черноземье": "в Черноземье"}
    out = {}
    blok3 = t[t.find("3 класса"):t.find("4 класса")]
    for nazv, kak in reg.items():
        m = re.search(kak + r"[^.;]*?(?:на|-)\s*([\d ]+)\s*рубл[^.;]*?до\s*([\d ]+)\s*рубл", blok3)
        if m:
            out[nazv] = {"cena": chislo(m.group(2)), "izm": chislo(m.group(1))}
    if "Сибирь" not in out:
        return None
    d = re.search(r"(\d{1,2}) (\w+)\. INTERFAX", t)
    data = dt.date(segodnya.year, MESYACY[d.group(2)], int(d.group(1))) if d and d.group(2) in MESYACY else segodnya
    return {"data": data.isoformat(), "istochnik": url, "klass3": out,
            "sleduyushchij": f"{data + dt.timedelta(days=7):%d.%m}"}


def sobrat_ceny(zapros, kesh, segodnya, oshibki):
    """Свежий мониторинг из ленты Интерфакса. Не вышло: последние проверенные цены из кэша.

    Возвращает (цены, обновлён_ли_кэш). Записывать кэш на диск решает вызывающий.
    """
    try:
        rss = zapros("https://www.interfax.ru/rss.asp", tajmaut=12)
        for m in re.finditer(r"<item>(.*?)</item>", rss, re.S):
            zag = re.search(r"<title>(.*?)</title>", m.group(1)).group(1)
            if "ПроЗерно" in zag or ("пшениц" in zag and "цен" in zag):
                url = re.search(r"<link>(.*?)</link>", m.group(1)).group(1)
                novye = razobrat_prozerno(tekst(zapros(url)), url, segodnya)
                if novye and novye["data"] > kesh["data"]:
                    return novye, True
                break
    except Exception as e:
        oshibki.append(f"Интерфакс недоступен, цены из последнего проверенного мониторинга: {type(e).__name__}")
    return kesh, False


# ---------- Погода ----------
def pogoda_open_meteo(zapros, la, lo):
    j = json.loads(zapros(
        f"https://api.open-meteo.com/v1/forecast?latitude={la}&longitude={lo}"
        "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum,snowfall_sum&forecast_days=3&timezone=auto",
        tajmaut=8))
    d = j["daily"]
    return {"tmin": min(d["temperature_2m_min"]), "tmax": max(d["temperature_2m_max"]),
            "osadki": sum(d["precipitation_sum"]), "sneg": sum(d["snowfall_sum"]), "ist": "Open-Meteo"}


def pogoda_met_no(zapros, la, lo):
    """Запасной источник: met.no отвечает из России без VPN. Осадки по 6-часовым интервалам на 72 часа."""
    j = json.loads(zapros(f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={la}&lon={lo}", tajmaut=15))
    ts = j["properties"]["timeseries"]
    nachalo = dt.datetime.fromisoformat(ts[0]["time"].replace("Z", "+00:00"))
    temp, osadki, sneg = [], 0.0, 0.0
    for t in ts:
        vremya = dt.datetime.fromisoformat(t["time"].replace("Z", "+00:00"))
        if (vremya - nachalo).total_seconds() > 72 * 3600:
            break
        temp.append(t["data"]["instant"]["details"]["air_temperature"])
        if vremya.hour % 6 == 0 and "next_6_hours" in t["data"]:
            n6 = t["data"]["next_6_hours"]
            mm = n6.get("details", {}).get("precipitation_amount", 0.0)
            osadki += mm
            if re.search(r"snow|sleet", n6.get("summary", {}).get("symbol_code", "")):
                sneg += mm  # мм водного эквивалента, ~1 см снега на мм
    return {"tmin": min(temp), "tmax": max(temp), "osadki": osadki, "sneg": sneg, "ist": "MET Norway"}


def sobrat_pogodu(zapros, rajony, oshibki):
    res = {}
    for gorod, (la, lo) in rajony.items():
        posled = None
        for istochnik in (pogoda_open_meteo, pogoda_met_no):
            try:
                res[gorod] = istochnik(zapros, la, lo)
                break
            except Exception as e:
                posled = e
        else:
            oshibki.append(f"погода {gorod}: {posled}")
    return res
