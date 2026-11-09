// Калькулятор сделки на странице. Формулы те же, что в raschet.py: sdelka().
// Совпадение проверяет tests/test_svodka.py на примерах из examples/sdelki.json.
function schetSdelki(v, z, pr, l, pp, d, s) {
  const vyruchka = pr * v, zakupka = z * v, logist = l * v;
  const dengi = zakupka * pp / 100 * s / 100 * d / 365;
  const marzha = vyruchka - zakupka - logist - dengi;
  const doDeneg = vyruchka - zakupka - logist;
  return {
    vyruchka: vyruchka,
    dengi: dengi,
    do_deneg: doDeneg,
    marzha: marzha,
    marzha_proc: vyruchka ? marzha / vyruchka * 100 : 0,
    dolya_deneg_proc: doDeneg > 0 ? dengi / doDeneg * 100 : 0,
    cena_v_nol: v ? (zakupka + logist + dengi) / v : 0,
    za_10_rub: 10 * v,
    minus_10_dney: zakupka * pp / 100 * s / 100 * 10 / 365
  };
}
if (typeof module !== "undefined") { module.exports = { schetSdelki }; }
