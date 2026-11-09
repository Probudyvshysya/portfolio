"""Расшифровка записи собеседования локально, без интернета (после первой загрузки моделей).

Нарезка: Silero VAD -> куски речи до 22 с (GigaAM принимает не длиннее 25 с).
Одна и та же нарезка для GigaAM и Whisper, чтобы сравнение было честным.

Примеры:
  python rasshifrovat.py audio.wav --model gigaam
  python rasshifrovat.py audio.wav --model whisper --whisper-name large-v3-turbo
Результат: <имя>.<модель>.txt (строки "[мм:сс] текст") и <имя>.<модель>.json (куски + замеры).
"""

import argparse
import json
import os
import time
from pathlib import Path

import soundfile as sf
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

SR = 16000
# Щадящий режим: тяжёлым задачам — не больше HR_POTOKI потоков процессора (по умолчанию 4),
# чтобы ПК не работал на пределе и оставался отзывчивым
POTOKI = int(os.environ.get("HR_POTOKI", 4))
MAX_CHUNK_S = 22.0
MERGE_GAP_S = 0.6


def load_wav(path):
    wav, sr = sf.read(path, dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    if sr != SR:
        raise SystemExit(f"Нужен WAV 16 кГц, а у файла {sr} Гц. Перегнать: ffmpeg -i in -ac 1 -ar 16000 out.wav")
    return torch.from_numpy(wav)


def narezat(wav):
    """Куски речи по VAD; соседние склеиваются, пока пауза короткая и кусок не длиннее MAX_CHUNK_S."""
    vad = load_silero_vad(onnx=True)
    ts = get_speech_timestamps(
        wav, vad, sampling_rate=SR,
        min_silence_duration_ms=300, speech_pad_ms=150,
        max_speech_duration_s=MAX_CHUNK_S,
    )
    chunks = []
    for t in ts:
        s, e = t["start"], t["end"]
        if chunks and (s - chunks[-1][1]) / SR <= MERGE_GAP_S and (e - chunks[-1][0]) / SR <= MAX_CHUNK_S:
            chunks[-1][1] = e
        else:
            chunks.append([s, e])
    return chunks


def gigaam_engine(name):
    import gigaam

    model = gigaam.load_model(name, fp16_encoder=False, device="cpu")

    @torch.inference_mode()
    def run(piece):
        wav = piece.unsqueeze(0)
        length = torch.full([1], wav.shape[-1])
        enc, enc_len = model.forward(wav, length)
        text, _ = model._decode(enc, enc_len, length, False)[0]
        return text

    return run


def whisper_engine(name, device, compute):
    from faster_whisper import WhisperModel

    model = WhisperModel(name, device=device, compute_type=compute)

    def run(piece):
        segs, _ = model.transcribe(
            piece.numpy(), language="ru", beam_size=5,
            condition_on_previous_text=False, vad_filter=False,
        )
        return " ".join(s.text.strip() for s in segs)

    return run


def mmss(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--model", choices=["gigaam", "whisper"], required=True)
    ap.add_argument("--gigaam-name", default="v3_e2e_rnnt")
    ap.add_argument("--whisper-name", default="large-v3-turbo")
    ap.add_argument("--whisper-device", default="cpu")
    ap.add_argument("--whisper-compute", default="int8")
    ap.add_argument("--threads", type=int, default=POTOKI)
    ap.add_argument("--limit-s", type=float, default=0, help="обработать только первые N секунд (для пробы)")
    a = ap.parse_args()

    torch.set_num_threads(a.threads)
    wav = load_wav(a.wav)
    if a.limit_s:
        wav = wav[: int(a.limit_s * SR)]
    dur = len(wav) / SR

    t0 = time.perf_counter()
    chunks = narezat(wav)
    t_vad = time.perf_counter() - t0

    t0 = time.perf_counter()
    if a.model == "gigaam":
        run, tag = gigaam_engine(a.gigaam_name), a.gigaam_name
    else:
        run, tag = whisper_engine(a.whisper_name, a.whisper_device, a.whisper_compute), f"whisper-{a.whisper_name}-{a.whisper_device}"
    t_load = time.perf_counter() - t0

    out, t0 = [], time.perf_counter()
    for i, (s, e) in enumerate(chunks, 1):
        text = run(wav[s:e]).strip()
        out.append({"start": round(s / SR, 2), "end": round(e / SR, 2), "text": text})
        if i % 20 == 0:
            print(f"  {i}/{len(chunks)} кусков, {mmss(e / SR)} из {mmss(dur)}", flush=True)
    t_asr = time.perf_counter() - t0

    speech = sum(e - s for s, e in chunks) / SR
    zamery = {
        "model": tag, "threads": a.threads, "audio_s": round(dur, 1), "speech_s": round(speech, 1),
        "chunks": len(chunks), "vad_s": round(t_vad, 1), "load_s": round(t_load, 1),
        "asr_s": round(t_asr, 1), "rtf": round(t_asr / dur, 3),
    }
    base = Path(a.wav).with_suffix("")
    stem = f"{base}.{tag}" + (f".first{int(a.limit_s)}s" if a.limit_s else "")
    Path(stem + ".txt").write_text("\n".join(f"[{mmss(c['start'])}] {c['text']}" for c in out) + "\n", encoding="utf-8")
    Path(stem + ".json").write_text(json.dumps({"zamery": zamery, "chunks": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(zamery, ensure_ascii=False))


if __name__ == "__main__":
    main()
