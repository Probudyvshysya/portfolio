"""Сторож сроков: раз в сутки смотрит календарь и напоминает за 14, 7, 3, 1 день и в день срока.

Почему не отдельная cron-строка на каждую дату: в cron нет года, и задача «28 октября» сработает и через год
с устаревшей суммой. Здесь дата хранится с годом, прошедшие сроки сами выпадают.
Журнал отправленных не даёт напомнить дважды, если cron запустился повторно в тот же день.
"""

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from .sroki import Srok

PORA = (14, 7, 3, 1, 0)


def rub(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def dney(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def tekst(srok: Srok, ostalos: int) -> str:
    shapka = {0: "СЕГОДНЯ КРАЙНИЙ СРОК", 1: "ЗАВТРА КРАЙНИЙ СРОК"}.get(ostalos, f"Осталось {ostalos} {dney(ostalos)}")
    stroki = [shapka, srok.chto, f"Срок: {srok.data:%d.%m.%Y}"]
    if srok.summa:
        stroki.append(f"Сумма: {rub(srok.summa)}")
    stroki.append(f"Основание: {srok.istochnik}")
    return "\n".join(stroki)


class Storozh:
    def __init__(self, sroki: list[Srok], zhurnal: Path, poslat: Callable[[str], bool]):
        self.sroki, self.zhurnal, self.poslat = sroki, Path(zhurnal), poslat

    def _prochitat(self) -> dict:
        try:
            return json.loads(self.zhurnal.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def segodnya_nado(self, segodnya: date) -> list[tuple[Srok, int]]:
        bylo = self._prochitat()
        out = []
        for s in self.sroki:
            ost = (s.data - segodnya).days
            if ost in PORA and f"{s.data.isoformat()}@{ost}" not in bylo:
                out.append((s, ost))
        return out

    def progon(self, segodnya: date) -> int:
        """Отправляет то, что положено сегодня. Неотправленное в журнал не пишется и уйдёт при следующем запуске."""
        bylo = self._prochitat()
        ushlo = 0
        for s, ost in self.segodnya_nado(segodnya):
            if self.poslat(tekst(s, ost)):
                bylo[f"{s.data.isoformat()}@{ost}"] = datetime.now().isoformat(timespec="seconds")
                ushlo += 1
        self.zhurnal.parent.mkdir(parents=True, exist_ok=True)
        self.zhurnal.write_text(json.dumps(bylo, ensure_ascii=False, indent=1), encoding="utf-8")
        return ushlo


def v_konsol(t: str) -> bool:
    print("-" * 60)
    print(t)
    return True


def telegram_iz_okruzheniya() -> Callable[[str], bool] | None:
    """Отправка в Telegram, если заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID. Токен в вывод не печатается."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tok or not chat:
        return None

    def poslat(t: str) -> bool:
        data = urllib.parse.urlencode({"chat_id": chat, "text": t}).encode()
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=25) as r:
                return bool(json.loads(r.read().decode()).get("ok"))
        except Exception as e:  # сеть или лимиты не должны ронять cron
            print(f"Не отправлено: {type(e).__name__}")
            return False

    return poslat
