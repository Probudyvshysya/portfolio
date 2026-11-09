"""Проверка установки HR-помощника. Запуск: .venv\\Scripts\\python PROVERKA.py

По каждому пункту — ✅ или ❌ и что сделать. Ничего не меняет и никуда не отправляет.
"""

import json
import os
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

KOREN = Path(__file__).resolve().parent
sys.path.insert(0, str(KOREN))
MODEL = "qwen3:4b-instruct-2507-q4_K_M"
PORT = 8790
itog = []


def punkt(nazv, ok, chto_delat=""):
    itog.append(ok)
    print(f"{'✅' if ok else '❌'} {nazv}" + ("" if ok else f"\n   → {chto_delat}"))


def postoyannaya(k):
    """Переменная пользователя из реестра (то, что ставит setx)."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, k)[0]
    except (ImportError, OSError):  # не Windows (сервер на Linux): настройки там задаются в службе Ollama
        return None


def main():
    print("Проверка HR-помощника\n")
    punkt(f"Python {sys.version.split()[0]}", sys.version_info[:2] == (3, 12), "нужен Python 3.12 (из комплекта)")

    for mod in ["torch", "gigaam", "silero_vad", "sherpa_onnx", "soundfile", "soundcard", "fastapi", "uvicorn"]:
        try:
            __import__(mod)
            punkt(f"библиотека {mod}", True)
        except Exception as e:
            punkt(f"библиотека {mod}", False, f"pip install --no-index --find-links kolesa -r requirements-lock.txt ({e})")

    punkt("ffmpeg (чтение mp3/mp4/m4a)", shutil.which("ffmpeg") is not None, "положить ffmpeg.exe из комплекта в PATH")

    g = Path.home() / ".cache" / "gigaam" / "v3_e2e_rnnt.ckpt"
    punkt("модель распознавания GigaAM-v3", g.exists() and g.stat().st_size > 100e6,
          f"скопировать v3_e2e_rnnt.ckpt и v3_e2e_rnnt_tokenizer.model в {g.parent}")
    m = KOREN / "modeli"
    punkt("модели деления по голосам", (m / "wespeaker_en_voxceleb_resnet34_LM.onnx").exists()
          and (m / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").exists(), f"скопировать папку modeli в {m}")

    try:
        tags = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3))
        punkt("Ollama запущен", True)
        punkt(f"модель {MODEL}", any(t["name"] == MODEL for t in tags["models"]),
              "скопировать модели Ollama из комплекта в %USERPROFILE%\\.ollama\\models")
    except Exception:
        punkt("Ollama запущен", False, "запустить ZAPUSK.cmd или установить Ollama из комплекта")
    # важны для процесса Ollama, а не для этого окна; ZAPUSK.cmd ставит их сам. Опасно, только если Ollama
    # стартует из автозагрузки без них — тогда нужны постоянные переменные пользователя.
    for k, v in {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}.items():
        if os.environ.get(k) == v or postoyannaya(k) == v:
            punkt(f"настройка {k}={v}", True)
        else:
            print(f"⚠ настройка {k}={v} не постоянная — ZAPUSK.cmd ставит её сам. Если Ollama запускается из "
                  f"автозагрузки, выполните: setx {k} {v}")

    try:
        from hr.zapis import ustroystva

        u = ustroystva()["nazvaniya"]
        punkt(f"микрофон: {u['mikrofon']}", True)
        punkt(f"звук компьютера (для записи собеседника): {u['zvuk']}", True)
    except Exception as e:
        punkt("микрофон и звук компьютера", False, f"проверить звуковые устройства Windows ({e})")

    try:
        import psutil

        ozu = psutil.virtual_memory().total / 2**30
        punkt(f"оперативная память {ozu:.0f} ГБ", ozu >= 15, "нужно 16 ГБ")
    except ImportError:
        pass
    svob = shutil.disk_usage(KOREN).free / 2**30
    punkt(f"свободно на диске {svob:.0f} ГБ", svob >= 10, "освободить хотя бы 10 ГБ (записи ~100 МБ на час)")

    s = socket.socket()
    try:
        s.bind(("127.0.0.1", PORT))
        punkt(f"порт {PORT} свободен", True)
    except OSError:
        try:
            d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/sostoyanie", timeout=2))
            punkt(f"порт {PORT}: HR-помощник уже запущен", d.get("prilozhenie") == "hr-pomoshchnik",
                  f"порт {PORT} занят другой программой — поменять PORT в hr/server.py и ZAPUSK.cmd")
        except Exception:
            punkt(f"порт {PORT} свободен", False, f"порт {PORT} занят другой программой — поменять PORT в hr/server.py")
    finally:
        s.close()

    print(f"\nИтог: {sum(itog)} из {len(itog)} в порядке" + ("" if all(itog) else " — исправьте пункты с ❌"))
    return 0 if all(itog) else 1


if __name__ == "__main__":
    sys.exit(main())
