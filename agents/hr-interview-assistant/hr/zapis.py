"""Запись созвона в две дорожки: микрофон HR и звук компьютера (собеседник в Telemost/Zoom/любой программе).

Пишется сразу на диск по кускам в «сырой» звук без заголовка (.raw) — если программа упадёт посреди созвона,
записанное сохранится и прочитается. По «Стоп» сырой звук переводится в WAV.
В конце дорожки выравниваются по длине и собирается общая дорожка для прослушивания.
"""

import threading
import time
import warnings

import numpy as np
import soundfile as sf

SR = 16000
BLOK = SR // 10  # 0,1 с

# soundcard 0.4.5 вызывает np.fromstring, которого нет в numpy 2
if not hasattr(np, "_fromstring_orig"):
    np._fromstring_orig = np.fromstring
    np.fromstring = lambda b, dtype=float, **k: np.frombuffer(b, dtype=dtype).copy()

warnings.filterwarnings("ignore", module="soundcard")


def ustroystva():
    import soundcard as sc

    spk, mic = sc.default_speaker(), sc.default_microphone()
    petlya = sc.get_microphone(id=str(spk.name), include_loopback=True)
    return {"mikrofon": mic, "petlya": petlya, "nazvaniya": {"mikrofon": mic.name, "zvuk": spk.name}}


class Zapis:
    def __init__(self):
        self.kandidat_id = None
        self.papka = None
        self.t0 = None
        self.uroven = {"hr": 0.0, "kandidat": 0.0}
        self._stop = threading.Event()
        self._potoki = []
        self.oshibka = None

    def idet(self):
        return self.kandidat_id is not None

    def _pisat(self, dev, put, klyuch):
        try:
            with sf.SoundFile(put, "w", SR, 1, "PCM_16", format="RAW") as f, dev.recorder(samplerate=SR, channels=1, blocksize=BLOK) as r:
                while not self._stop.is_set():
                    a = r.record(numframes=BLOK)[:, 0]
                    self.uroven[klyuch] = float(np.abs(a).max()) if len(a) else 0.0
                    f.write(a)
        except Exception as e:
            self.oshibka = f"{klyuch}: {type(e).__name__}: {e}"

    def nachat(self, kandidat_id, papka):
        if self.idet():
            raise RuntimeError("запись уже идёт")
        u = ustroystva()
        self.kandidat_id, self.papka, self.t0, self.oshibka = kandidat_id, papka, time.time(), None
        self._stop.clear()
        self._potoki = [
            threading.Thread(target=self._pisat, args=(u["mikrofon"], papka / "hr.raw", "hr"), daemon=True),
            threading.Thread(target=self._pisat, args=(u["petlya"], papka / "kandidat.raw", "kandidat"), daemon=True),
        ]
        for t in self._potoki:
            t.start()
        return u["nazvaniya"]

    def sostoyanie(self):
        if not self.idet():
            return {"idet": False}
        return {"idet": True, "kandidat_id": self.kandidat_id, "sekund": round(time.time() - self.t0),
                "uroven": {k: round(v, 3) for k, v in self.uroven.items()}, "oshibka": self.oshibka}

    def ostanovit(self):
        if not self.idet():
            raise RuntimeError("запись не идёт")
        self._stop.set()
        for t in self._potoki:
            t.join(timeout=5)
        papka, i = self.papka, self.kandidat_id
        self.kandidat_id = self.papka = None
        dlit = vyrovnyat_i_smeshat(papka)
        return i, dlit


def _prochitat(papka, imya):
    raw, wav = papka / f"{imya}.raw", papka / f"{imya}.wav"
    if raw.exists():
        return sf.read(raw, dtype="float32", samplerate=SR, channels=1, subtype="PCM_16", format="RAW")[0]
    return sf.read(wav, dtype="float32")[0]


def vyrovnyat_i_smeshat(papka):
    """hr/kandidat (.raw или .wav) -> WAV одной длины + общая дорожка proslushka.wav. Возвращает длительность, с."""
    a, b = _prochitat(papka, "hr"), _prochitat(papka, "kandidat")
    n = max(len(a), len(b))
    a, b = np.pad(a, (0, n - len(a))), np.pad(b, (0, n - len(b)))
    sf.write(papka / "hr.wav", a, SR, "PCM_16")
    sf.write(papka / "kandidat.wav", b, SR, "PCM_16")
    sf.write(papka / "proslushka.wav", np.clip(a + b, -1, 1), SR, "PCM_16")
    for imya in ("hr", "kandidat"):
        (papka / f"{imya}.raw").unlink(missing_ok=True)
    return round(n / SR, 1)
