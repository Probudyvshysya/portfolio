import sys

from .cli import main

# Консоль Windows по умолчанию в cp1251: без этого знак ₽ роняет вывод в файл или через конвейер
for potok in (sys.stdout, sys.stderr):
    if hasattr(potok, "reconfigure"):
        potok.reconfigure(encoding="utf-8")

sys.exit(main())
