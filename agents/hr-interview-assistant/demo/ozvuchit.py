"""Озвучка демо-собеседования локально (Silero TTS v4_ru, только для тестов: лицензия CC BY-NC-SA).

Пишет рядом со сценарием:
  sobes-hr.wav        — дорожка интервьюера (как микрофон HR)
  sobes-kandidat.wav  — дорожка кандидата (как звук созвона)
  sobes-mix.wav       — обе в одной дорожке (как запись с телефона)
Все 16 кГц моно, дорожки выровнены по времени.
"""

import argparse
import re
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

HERE = Path(__file__).parent
SR_TTS, SR = 48000, 16000
VOICE = {"HR": "baya", "К": "aidar"}
ZAMENY = {"1С": "один эс", "ФГИС": "эф гис", "СДИЗ": "сдиз", "НДС": "эн дэ эс", "КФХ": "кэ эф ха"}


def chistka(t):
    for k, v in ZAMENY.items():
        t = t.replace(k, v)
    return t.replace("…", ",").replace("«", "").replace("»", "").replace(" — ", ", ").replace("—", ", ").replace("–", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenariy", default="scenariy-sobesedovaniya.txt")
    ap.add_argument("--golos", default="aidar", help="голос кандидата: aidar, eugene, xenia, kseniya")
    ap.add_argument("--imya", default="sobes", help="приставка файлов: <imya>-hr.wav, <imya>-kandidat.wav")
    a = ap.parse_args()
    VOICE["К"] = a.golos
    model, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language="ru", speaker="v4_ru", trust_repo=True)
    lines = []
    for raw in (HERE / a.scenariy).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(HR|К): (.+)$", raw.strip())
        if m:
            lines.append(m.groups())

    tracks = {"HR": [], "К": []}
    rng = np.random.default_rng(7)
    for who, text in lines:
        parts = []
        for sent in re.split(r"(?<=[.!?])\s+", chistka(text)):
            if sent.strip():
                zvuk = model.apply_tts(text=sent, speaker=VOICE[who], sample_rate=SR_TTS, put_accent=True, put_yo=True)
                parts.append(zvuk.numpy()[::3])  # 48 -> 16 кГц
                parts.append(np.zeros(int(SR * 0.25), dtype=np.float32))
        speech = np.concatenate(parts)
        pause = np.zeros(int(SR * rng.uniform(0.5, 1.2)), dtype=np.float32)
        other = "К" if who == "HR" else "HR"
        tracks[who] += [speech, pause]
        tracks[other] += [np.zeros_like(speech), pause]

    hr, k = np.concatenate(tracks["HR"]), np.concatenate(tracks["К"])
    mix = hr + k + rng.normal(0, 0.003, len(hr)).astype(np.float32)  # лёгкий шум, как в жизни
    for name, dor in [("hr", hr), ("kandidat", k), ("mix", mix)]:
        sf.write(HERE / f"{a.imya}-{name}.wav", np.clip(dor, -1, 1), SR)
    print(f"готово: {len(lines)} реплик, {len(hr) / SR / 60:.1f} мин")


if __name__ == "__main__":
    main()
