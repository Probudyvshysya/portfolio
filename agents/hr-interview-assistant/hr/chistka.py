"""Удаление данных отказанных кандидатов через срок после решения «Отказ» (по умолчанию 30 дней).

В журнале остаётся только id и даты, без ФИО и без содержания.
Срок выбирает юрист компании: 30 дней (цель обработки достигнута, ч. 4 ст. 21 152-ФЗ) или дольше, например
3 месяца на случай спора об отказе в приёме (ст. 392 ТК). Задаётся переменной HR_SROK_DNEY.
"""

import os
import shutil
from datetime import datetime, timedelta

from . import hranilishche as H

SROK_DNEY = int(os.environ.get("HR_SROK_DNEY", 30))


def pochistit(seychas=None, dney=SROK_DNEY):
    seychas = seychas or datetime.now()
    udaleno = []
    for k in H.spisok_kandidatov():
        if k.get("reshenie") != "отказ" or not k.get("reshenie_data"):
            continue
        if seychas - datetime.fromisoformat(k["reshenie_data"]) >= timedelta(days=dney):
            with H.LOCK:
                shutil.rmtree(H.papka(k["id"]), ignore_errors=True)
            H.zhurnal(f"удалены данные кандидата {k['id']} (отказ {k['reshenie_data'][:10]}, срок {dney} дн.)")
            udaleno.append(k["id"])
    from . import otkliki

    for x in otkliki.spisok():  # отклики: срок считаем от отправленного отказа
        p = x.get("pismo") or {}
        if p.get("tip") == "отказ" and p.get("status") == "отправлено" and p.get("kogda") \
                and seychas - datetime.fromisoformat(p["kogda"]) >= timedelta(days=dney):
            otkliki.udalit(x["id"])
            H.zhurnal(f"удалено резюме отклика {x['id']} (отказ {p['kogda'][:10]}, срок {dney} дн.)")
            udaleno.append(x["id"])
    return udaleno
