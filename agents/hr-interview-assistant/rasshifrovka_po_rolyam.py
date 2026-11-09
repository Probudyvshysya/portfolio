"""Расшифровка собеседования с подписью, кто говорит.

Две дорожки (основной путь): микрофон HR и звук собеседника — подпись по дорожке, без угадывания.
  python rasshifrovka_po_rolyam.py --hr hr.wav --kandidat kandidat.wav -o sobes
Одна дорожка (запасной путь): деление по голосам (sherpa-onnx), подписи «Голос 1/2/…».
  python rasshifrovka_po_rolyam.py --odna mix.wav -o sobes
Результат: sobes.rasshifrovka.txt ("[мм:сс] Кто: текст") и sobes.rasshifrovka.json
"""

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

import soundfile as sf
import torch

from rasshifrovat import POTOKI, SR, gigaam_engine, mmss, narezat

M = Path(__file__).parent / "modeli"


def k_16k(path):
    """Любой аудио/видеофайл -> 16 кГц моно float32 (через ffmpeg)."""
    data, sr = None, None
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception:
        pass
    if sr != SR or data is None:
        tmp = Path(tempfile.gettempdir()) / f"hr_{Path(path).stem}_16k.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", str(SR), str(tmp)], check=True)
        data, sr = sf.read(tmp, dtype="float32", always_2d=True)
        tmp.unlink(missing_ok=True)
    return torch.from_numpy(data.mean(axis=1))


def rasshifrovat_dorozhku(wav, kto, run):
    out = []
    for s, e in narezat(wav):
        text = run(wav[s:e]).strip()
        if text:
            out.append({"start": round(s / SR, 2), "end": round(e / SR, 2), "kto": kto, "text": text})
    return out


def razdelit_golosa(wav):
    import sherpa_onnx

    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(M / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx")), num_threads=POTOKI),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(M / "wespeaker_en_voxceleb_resnet34_LM.onnx"), num_threads=POTOKI),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
        min_duration_on=0.3, min_duration_off=0.5,
    )
    segs = sherpa_onnx.OfflineSpeakerDiarization(cfg).process(wav.numpy()).sort_by_start_time()
    segs = [(r.start, r.end, r.speaker) for r in segs]
    # мелкие «голоса» (< 3 % речи) — обрывки вроде «угу»: отдаём ближайшему соседу по времени
    tot = {}
    for s, e, k in segs:
        tot[k] = tot.get(k, 0) + e - s
    big = {k for k, v in tot.items() if v >= 0.03 * sum(tot.values())}
    fixed = []
    for i, (s, e, k) in enumerate(segs):
        if k not in big:
            near = [x for x in segs if x[2] in big]
            k = min(near, key=lambda x: min(abs(x[0] - e), abs(x[1] - s)))[2] if near else k
        fixed.append((s, e, k))
    nomer = {k: n for n, k in enumerate(sorted(big, key=lambda k: -tot[k]), 1)}
    return [(s, e, f"Голос {nomer.get(k, '?')}") for s, e, k in fixed]


def ubrat_eho(reps, porog=0.6):
    """Без наушников микрофон HR ловит голос кандидата из колонок: такие повторы в дорожке HR убираем."""
    import difflib

    kand = [r for r in reps if r["kto"] == "Кандидат"]
    out = []
    for r in reps:
        if r["kto"] == "HR":
            for k in kand:
                peresekayutsya = min(r["end"], k["end"]) - max(r["start"], k["start"]) > 0
                if peresekayutsya and difflib.SequenceMatcher(None, r["text"].lower(), k["text"].lower()).ratio() >= porog:
                    break
            else:
                out.append(r)
        else:
            out.append(r)
    return out


def skleit(reps):
    """Подряд идущие реплики одного человека — в одну."""
    out = []
    for r in sorted(reps, key=lambda r: r["start"]):
        if out and out[-1]["kto"] == r["kto"] and r["start"] - out[-1]["end"] < 2.0:
            out[-1]["text"] += " " + r["text"]
            out[-1]["end"] = r["end"]
        else:
            out.append(dict(r))
    return out


def rasshifrovat(hr=None, kandidat=None, odna=None, run=None):
    """Главная функция для импорта: возвращает список реплик {start, end, kto, text}."""
    run = run or gigaam_engine("v3_e2e_rnnt")
    reps = []
    if hr and kandidat:
        reps += rasshifrovat_dorozhku(k_16k(hr), "HR", run)
        reps += rasshifrovat_dorozhku(k_16k(kandidat), "Кандидат", run)
        reps = ubrat_eho(reps)
    elif odna:
        wav = k_16k(odna)
        for s, e, kto in razdelit_golosa(wav):
            piece = wav[int(s * SR):int(e * SR)]
            for r in rasshifrovat_dorozhku(piece, kto, run):
                reps.append({**r, "start": round(r["start"] + s, 2), "end": round(r["end"] + s, 2)})
    else:
        raise ValueError("Нужно hr и kandidat, или odna")
    return primenit_slovar(skleit(reps))


SLOVAR = Path(__file__).parent / "znaniya" / "slovar-zamen.txt"


def zagruzit_slovar(put=SLOVAR):
    import re

    pravila = []
    if put.exists():
        for stroka in put.read_text(encoding="utf-8").splitlines():
            if stroka.strip() and not stroka.lstrip().startswith("#") and "=>" in stroka:
                chto, na = (x.strip() for x in stroka.split("=>", 1))
                pravila.append((re.compile(chto, re.I), na))
    return pravila


def primenit_slovar(repliki, pravila=None):
    """Исправляем типичные ослышки распознавания (аббревиатуры, термины) по словарю компании."""
    pravila = zagruzit_slovar() if pravila is None else pravila
    for r in repliki:
        for rx, na in pravila:
            r["text"] = rx.sub(na, r["text"])
        r["text"] = r["text"].replace("СДИЗЗ", "СДИЗ").replace("  ", " ")
    return repliki


def v_tekst(repliki):
    return "\n".join(f"[{mmss(r['start'])}] {r['kto']}: {r['text']}" for r in repliki) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hr")
    ap.add_argument("--kandidat")
    ap.add_argument("--odna")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    torch.set_num_threads(POTOKI)

    if not ((a.hr and a.kandidat) or a.odna):
        raise SystemExit("Нужно --hr и --kandidat, или --odna")
    t0 = time.perf_counter()
    sklejka = rasshifrovat(a.hr, a.kandidat, a.odna)

    dt = round(time.perf_counter() - t0, 1)
    Path(a.out + ".rasshifrovka.txt").write_text(v_tekst(sklejka), encoding="utf-8")
    Path(a.out + ".rasshifrovka.json").write_text(
        json.dumps({"vremya_s": dt, "repliki": sklejka}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"готово за {dt} с: {len(sklejka)} реплик -> {a.out}.rasshifrovka.txt")


if __name__ == "__main__":
    main()
