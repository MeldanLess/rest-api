"""Ждём, пока база данных начнёт принимать подключения.

Запускать перед стартом API и перед применением миграций, чтобы холодный старт
не падал с «connection refused», пока PostgreSQL ещё инициализируется.

    python scripts/wait_for_db.py [--timeout 60]
"""

import argparse
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout", type=int, default=60, help="сколько секунд ждать перед сдачей"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="пауза между попытками в секундах"
    )
    args = parser.parse_args()

    settings = get_settings()
    deadline = time.monotonic() + args.timeout
    attempt = 0

    while True:
        attempt += 1
        try:
            engine = create_engine(settings.database_url, pool_pre_ping=True)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            engine.dispose()
            print(f"База данных готова (попыток: {attempt}).")
            return 0
        except OperationalError as error:
            if time.monotonic() >= deadline:
                print(
                    f"База данных не поднялась за {args.timeout} с: {error}",
                    file=sys.stderr,
                )
                return 1
            print(f"Ждём базу данных... ({attempt})", file=sys.stderr)
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
