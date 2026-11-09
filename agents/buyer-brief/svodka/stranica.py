"""Одна HTML-страница сводки. Все числа приходят готовыми из raschet.py и pravila.py."""

import datetime as dt
import html
import re
from pathlib import Path

from . import pravila
from .nastroyki import Nastroyki
from .raschet import bez_nds, izm_proc, proc, rub, stoimost_deneg

KALKULYATOR_JS = (Path(__file__).resolve().parent / "kalkulyator.js").read_text(encoding="utf-8")

STIL = """
:root{--bg:#f5f4ef;--card:#fff;--ink:#1c1c1a;--mut:#6d6b64;--line:#e3e0d7;--up:#b3261e;--dn:#1d7a3a;--acc:#7a5200;--tag:#efe8d8;
--g:#2e9d55;--y:#d9a400;--r:#d0402f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15.5px/1.5 "Segoe UI",system-ui,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:22px 16px 40px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-bottom:14px}
h1{font-size:25px;margin:0}.sub{color:var(--mut);font-size:13.5px}
.badge{background:var(--tag);color:var(--acc);font-size:12.5px;padding:4px 10px;border-radius:999px}
.svs{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:12px}
.sv{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:grid;grid-template-columns:14px 1fr;column-gap:8px}
.sv b{font-size:14px}.sv small{grid-column:2;color:var(--mut);font-size:13px}
.dot{width:12px;height:12px;border-radius:50%;margin-top:4px}.green .dot{background:var(--g)}.yellow .dot{background:var(--y)}.red .dot{background:var(--r)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:12px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:0 0 10px}
.rynok p{margin:0;font-size:16.5px}
.cin{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:12px}
.cin label{font-size:12.5px;color:var(--mut);display:flex;flex-direction:column;gap:4px}
.cin input{font:inherit;font-size:16px;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:#fffdf7;color:var(--ink)}
.calc{border-left:4px solid var(--g)}.todo{border-left:4px solid var(--acc)}.todo ol{margin:0;padding-left:20px}.todo li{margin:6px 0}
.news{border-top:1px solid var(--line);padding:12px 0}.news:first-of-type{border-top:0;padding-top:0}
.nh{display:flex;gap:8px;align-items:center}.tag{background:var(--tag);color:var(--acc);font-size:12px;padding:2px 8px;border-radius:6px}
.dt{color:var(--mut);font-size:12.5px;font-variant-numeric:tabular-nums}
h3{font-size:16.5px;margin:6px 0 4px}h3 a{color:var(--ink);text-decoration:none}h3 a:hover{text-decoration:underline}
.news p{margin:4px 0}.imp{background:#faf6ea;border-radius:8px;padding:8px 10px;font-size:14.5px}
table{width:100%;border-collapse:collapse;font-size:14.5px}td,th{padding:7px 6px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:500;font-size:12.5px}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.my td{font-weight:600;background:#fbf7ec}.up{color:var(--up)}.dn{color:var(--dn)}
.keys{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:10px}
.k{border:1px solid var(--line);border-radius:8px;padding:9px 12px}.k span{color:var(--mut);font-size:12.5px;display:block}.k b{font-size:21px}.k small{display:block;font-size:12.5px}
.note{font-size:14px;color:#3a3935}.src{color:var(--mut);font-size:12px;margin-top:8px}.src a{color:var(--mut)}
.fon{columns:2 320px;padding-left:0;list-style:none;margin:0}.fon li{break-inside:avoid;margin:0 0 7px;font-size:14px}.fon a{color:var(--ink)}
details summary{cursor:pointer;color:var(--mut);font-size:13px}
.grid2{display:grid;grid-template-columns:1.4fr 1fr;gap:12px}@media(max-width:760px){.grid2{grid-template-columns:1fr}}
footer{color:var(--mut);font-size:12.5px;margin-top:14px}
"""

PODKLYUCHENIE = """
(function(){
  const f = n => Math.round(n).toLocaleString('ru-RU');
  const g = id => parseFloat(document.getElementById(id).value) || 0;
  function schet(){
    const r = schetSdelki(g('v'), g('z'), g('pr'), g('l'), g('pp'), g('d'), g('s'));
    document.getElementById('res').innerHTML =
      '<div class="k"><span>Маржа сделки</span><b class="' + (r.marzha < 0 ? 'up' : 'dn') + '">' + f(r.marzha) + ' ₽</b><small>' + r.marzha_proc.toFixed(1).replace('.', ',') + ' % от выручки</small></div>' +
      '<div class="k"><span>Цена в ноль</span><b>' + f(r.cena_v_nol) + ' ₽/т</b><small>продажа без НДС, ниже будет убыток</small></div>' +
      '<div class="k"><span>Деньги под предоплату</span><b>' + f(r.dengi) + ' ₽</b><small>' + (r.do_deneg > 0 ? 'съедают ' + r.dolya_deneg_proc.toFixed(0) + ' % маржи' : 'маржи нет и без них') + '</small></div>' +
      '<div class="k"><span>Каждые 10 ₽/т в цене</span><b>' + f(r.za_10_rub) + ' ₽</b><small>на этом объёме</small></div>' +
      '<div class="k"><span>Выручка</span><b>' + f(r.vyruchka) + ' ₽</b><small>без НДС</small></div>';
    document.getElementById('vyvod').textContent = r.marzha < 0
      ? 'Сделка в минусе: в ноль выходит при продаже от ' + f(r.cena_v_nol) + ' ₽/т. Проверьте цену продажи, логистику или срок предоплаты.'
      : 'Сократить заморозку денег на 10 дней = +' + f(r.minus_10_dney) + ' ₽ к марже этой сделки.';
  }
  document.querySelectorAll('.calc input').forEach(i => i.addEventListener('input', schet));
  schet();
})();
"""


def stranica(cb, novosti, ceny, pogoda, oshibki, segodnya, sobrano, nastr: Nastroyki = Nastroyki()):
    sv, p = pravila.svetofor(ceny, cb, novosti)
    dej = pravila.dejstviya(ceny, cb, novosti, p, nastr)
    glavnoe = [n for n in novosti if n["ball"] >= pravila.PROHODNOY_BALL][:5]
    fon = [n for n in novosti if n not in glavnoe and n["ball"] > -2
           and len(re.findall(r"[А-Яа-яЁё]", n["zag"])) > len(n["zag"]) / 3
           and not re.search(r"Котировки на зерновых биржах", n["zag"])
           and not re.search(pravila.CHUZHIE, n["zag"])][:10]
    e = html.escape

    vse = [(r, izm_proc(v["cena"], v["izm"])) for r, v in ceny["klass3"].items()]
    rost = all(x > 0 for _, x in vse)
    rynok = (f"Пшеница 3 класса {'дорожает во всех регионах' if rost else 'движется разнонаправленно'}: "
             f"{proc(min(x for _, x in vse))} … {proc(max(x for _, x in vse))}, Сибирь {proc(p)}. ")
    if cb:
        du = 100 * (cb["sejchas"]["USD"] - cb["ranshe"]["USD"]) / cb["ranshe"]["USD"]
        rynok += f"Доллар {proc(du)} за неделю. Ставка ЦБ {cb['stavka']:.0f} %. "
    if any(re.search(r"интервенц", n["zag"], re.I) for n in novosti):
        rynok += "Государство начинает закупки в интервенционный фонд."

    sv_html = "".join(f'<div class="sv {c}"><span class="dot"></span><b>{e(a)}</b><small>{e(t)}</small></div>' for a, c, t in sv)
    dej_html = "".join(f"<li>{e(x)}</li>" for x in dej)
    gl_html = ""
    for n in glavnoe:
        gl_html += (
            f'<article class="news"><div class="nh"><span class="tag">{e(n["kat"])}</span>'
            f'<span class="dt">{n["data"]:%d.%m}</span></div>'
            f'<h3><a href="{e(n["url"])}">{e(n["zag"])}</a></h3>'
            f'<p>{e(n.get("sut", ""))}</p>'
            + (f'<p class="imp"><b>Что это значит для нас:</b> {e(n["chto_znachit"])}</p>' if n.get("chto_znachit") else "")
            + "</article>")
    fon_html = "".join(f'<li><span class="dt">{n["data"]:%d.%m}</span> <a href="{e(n["url"])}">{e(n["zag"])}</a></li>' for n in fon)

    rows = ""
    for reg, v in sorted(ceny["klass3"].items(), key=lambda kv: -kv[1]["cena"]):
        pp = izm_proc(v["cena"], v["izm"])
        rows += (f'<tr class="{"my" if reg == "Сибирь" else ""}"><td>{e(reg)}</td><td class="n">{rub(v["cena"])}</td>'
                 f'<td class="n">{rub(bez_nds(v["cena"], nastr.nds))}</td>'
                 f'<td class="n {"up" if v["izm"] > 0 else "dn"}">{rub(v["izm"], True)}</td><td class="n">{proc(pp)}</td>'
                 f'<td class="n">{rub(v["izm"] * nastr.partiya_t, True)}</td></tr>')
    sib = ceny["klass3"]["Сибирь"]["cena"]
    razryv = {r: sib - v["cena"] for r, v in ceny["klass3"].items() if r != "Сибирь"}
    razryv_txt = ", ".join(f"{r} {rub(x, True)}" for r, x in sorted(razryv.items(), key=lambda kv: kv[1]))

    den = ""
    if cb:
        for kod, nazv in (("CNY", "Юань"), ("USD", "Доллар"), ("EUR", "Евро")):
            a, b = cb["sejchas"][kod], cb["ranshe"][kod]
            pp = 100 * (a - b) / b
            den += (f'<div class="k"><span>{nazv}, ЦБ</span><b>{a:.2f} ₽</b>'
                    f'<small class="{"up" if pp > 0 else "dn"}">{proc(pp)} за неделю</small></div>').replace(".", ",", 1)
        stavka = cb["stavka"] + nastr.nadbavka_banka
        st = stoimost_deneg(nastr.predoplata_rub, stavka, nastr.predoplata_dney)
        den = (f'<div class="k"><span>Ключевая ставка</span><b>{cb["stavka"]:.2f} %</b><small>на {cb["stavka_na"]}</small></div>'.replace(".", ",", 1)
               + den)
        den_vyvod = (f"Деньги под предоплату {rub(nastr.predoplata_rub)} ₽ на {nastr.predoplata_dney} дней при кредите около "
                     f"{stavka:.0f} % стоят около {rub(st)} ₽. Курс для сибирской закупки фон: "
                     f"рубль за неделю {'укрепился' if cb['sejchas']['USD'] < cb['ranshe']['USD'] else 'ослаб'}, "
                     "это влияет на экспортёров Юга сильнее, чем на нас.")
    else:
        den_vyvod = "Данные ЦБ сегодня недоступны."

    pog, spokojno = "", []
    for g, v in pogoda.items():
        zamet = "снег, возможны задержки вывоза" if v["sneg"] >= 2 else "дожди, проверить подъезды" if v["osadki"] >= 5 else ""
        if not zamet:
            spokojno.append(g)
            continue
        pog += (f'<tr><td>{e(g)}</td><td class="n">{v["tmin"]:.0f}…{v["tmax"]:.0f} °C</td>'
                f'<td class="n">{str(round(v["osadki"], 1)).replace(".", ",")} мм</td><td>{zamet}</td></tr>')

    data_cen = dt.date.fromisoformat(ceny["data"])
    stareet = (segodnya - data_cen).days
    osh = "".join(f"<li>{e(x)}</li>" for x in oshibki)
    zak_bez_nds = round(bez_nds(sib, nastr.nds))
    prod_bez_nds = round(bez_nds(sib, nastr.nds) * 1.06 / 10) * 10
    stavka_calc = (cb["stavka"] if cb else 14) + nastr.nadbavka_banka
    gorod = next(iter(nastr.rajony), "")

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Сводка закупщика</title>
<style>{STIL}</style></head><body><div class="wrap">
<header><div><h1>Утренняя сводка закупщика</h1>
<div class="sub">{segodnya:%d.%m.%Y} · собрано {sobrano:%H:%M} · {e(gorod)} · партия для расчёта {rub(nastr.partiya_t)} т</div></div>
<div class="badge">только открытые источники · данные компании не используются</div></header>

<div class="card rynok"><h2>Рынок за неделю</h2><p>{e(rynok)}</p></div>
<div class="svs">{sv_html}</div>

<div class="card todo"><h2>Что сделать сегодня</h2><ol>{dej_html}</ol></div>

<div class="card"><h2>Главное за неделю: что произошло и что это значит</h2>{gl_html}
<div class="src">Отбор по правилам: Сибирь, контрагенты, цены, экспорт, господдержка весят больше; новости других стран ниже</div></div>

<div class="grid2">
<div class="card"><h2>Пшеница 3 класса, ₽/т, EXW</h2>
<table><tr><th>Регион</th><th class="n">С НДС</th><th class="n">Без НДС</th><th class="n">За неделю</th><th class="n">%</th><th class="n">На партию</th></tr>{rows}</table>
<p class="note">Сибирь дороже других регионов: {razryv_txt} ₽/т. Выгодно ли везти зерно к нам из других регионов, решает ж/д тариф на маршрут; на внедрении подставим ваши тарифы и посчитаем точно. Сравнивайте цены без НДС: у хозяйства, освобождённого от НДС (часть хозяйств на ЕСХН), вычета не будет, и реальная стоимость для нас та же. НДС на зерно {nastr.nds} %. Изменение за неделю считано по цене с НДС.</p>
<div class="src">«ПроЗерно», мониторинг от {data_cen:%d.%m.%Y}{" · данным " + str(stareet) + " дн., следующий мониторинг " + ceny.get("sleduyushchij", "") if stareet > 2 else ""} · <a href="{e(ceny["istochnik"])}">источник</a></div></div>

<div class="card"><h2>Деньги</h2><div class="keys" style="grid-template-columns:1fr 1fr">{den}</div>
<p class="note">{e(den_vyvod)}</p>
<div class="src">Банк России: курсы на {cb["na"] if cb else "—"} к {cb["na_ranshe"] if cb else "—"}, ключевая ставка</div></div>
</div>

<div class="card calc"><h2>Калькулятор сделки: подставьте свои цифры</h2>
<div class="cin">
<label>Объём, т<input id="v" type="number" value="{nastr.partiya_t}" step="50"></label>
<label>Цена закупки, ₽/т без НДС<input id="z" type="number" value="{zak_bez_nds}" step="50"></label>
<label>Цена продажи, ₽/т без НДС<input id="pr" type="number" value="{prod_bez_nds}" step="50"></label>
<label>Логистика и хранение, ₽/т<input id="l" type="number" value="{nastr.logistika_t}" step="50"></label>
<label>Предоплата хозяйству, %<input id="pp" type="number" value="50" step="10"></label>
<label>Деньги заморожены, дней<input id="d" type="number" value="{nastr.predoplata_dney}" step="5"></label>
<label>Ставка кредита, %<input id="s" type="number" value="{stavka_calc:.0f}" step="0.5"></label>
</div>
<div class="keys" id="res"></div>
<p class="note" id="vyvod"></p>
<div class="src">Цифры по умолчанию для примера: закупка по «ПроЗерно» без НДС, продажа +6 %, логистика {nastr.logistika_t} ₽/т. Считает страница, интернет не нужен</div>
</div>
<script>{KALKULYATOR_JS}{PODKLYUCHENIE}</script>

<div class="card"><h2>Погода в районах закупки, 3 дня</h2>
{"<table><tr><th>Район</th><th class='n'>Температура</th><th class='n'>Осадки</th><th>Вывоз и погрузка</th></tr>" + pog + "</table>" if pog else ""}
<p class="note">{("Без помех: " + ", ".join(spokojno) + ".") if spokojno else ""}</p>
<div class="src">{", ".join(sorted({v["ist"] for v in pogoda.values()})) or "погода недоступна"}</div></div>

<div class="card"><h2>Остальное за неделю</h2><ul class="fon">{fon_html}</ul>
<div class="src">zerno.ru, новости за 7 дней</div></div>

<footer>Как это работает: сборщик на вашем компьютере каждое утро забирает открытые данные (ЦБ, отраслевые новости, недельные цены, погоду),
отбирает важное по правилам и считает влияние в рублях на ваши параметры. Цифры считает код, не нейросеть. На внедрении сюда добавляются
ваши цены закупки, районы хозяйств и список контрагентов для сверки.
{"<details><summary>Технические заметки сборщика</summary><ul>" + osh + "</ul></details>" if osh else ""}</footer>
</div></body></html>"""
