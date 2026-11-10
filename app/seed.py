"""Наполняет базу демо-пользователем и правдоподобным набором откликов.

Запуск:  python -m app.seed
Безопасно запускать повторно — дубликаты не создаются.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.crud import create_user, get_user_by_email
from app.database import SessionLocal
from app.enums import Priority, Source, Stage
from app.models import Application, ApplicationEvent
from app.schemas import ApplicationCreate
from app.security import hash_password

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo12345"

SAMPLES = [
    {
        "company": "Яндекс",
        "role": "Junior Python-разработчик",
        "location": "Москва",
        "source": Source.HH,
        "priority": Priority.HIGH,
        "stage": Stage.INTERVIEW,
        "salary_min": 120000,
        "salary_max": 160000,
        "notes": "Первый этап пройден. Готовлюсь к собеседованию на проектирование.",
        "created_days_ago": 21,
    },
    {
        "company": "Т-Банк",
        "role": "Стажировка Python Backend",
        "location": "Удалённо",
        "source": Source.TELEGRAM,
        "priority": Priority.HIGH,
        "stage": Stage.SCREENING,
        "salary_min": 90000,
        "salary_max": 120000,
        "notes": "Назначен звонок на скрининг.",
        "created_days_ago": 12,
    },
    {
        "company": "VK",
        "role": "Junior Backend-разработчик",
        "location": "Санкт-Петербург",
        "source": Source.HH,
        "priority": Priority.MEDIUM,
        "stage": Stage.APPLIED,
        "salary_min": 100000,
        "salary_max": 140000,
        "created_days_ago": 6,
    },
    {
        "company": "Сбер",
        "role": "Стажировка аналитика данных",
        "location": "Москва",
        "source": Source.REFERRAL,
        "priority": Priority.MEDIUM,
        "stage": Stage.OFFER,
        "salary_min": 80000,
        "salary_max": 100000,
        "notes": "Получил оффер, согласовываю дату выхода.",
        "created_days_ago": 45,
    },
    {
        "company": "Avito",
        "role": "Junior Python-разработчик",
        "location": "Удалённо",
        "source": Source.COMPANY_SITE,
        "priority": Priority.MEDIUM,
        "stage": Stage.REJECTED,
        "salary_min": 150000,
        "salary_max": 200000,
        "notes": "Отказ после технического интервью — не хватило проектирования.",
        "created_days_ago": 30,
    },
    {
        "company": "Kaspersky",
        "role": "Стажировка Python-разработчика",
        "location": "Москва",
        "source": Source.UNIVERSITY,
        "priority": Priority.LOW,
        "stage": Stage.SCREENING,
        "salary_min": 70000,
        "salary_max": 90000,
        "created_days_ago": 9,
    },
    {
        "company": "Ozon",
        "role": "Junior Backend-инженер",
        "location": "Удалённо",
        "source": Source.HH,
        "priority": Priority.LOW,
        "stage": Stage.WITHDRAWN,
        "salary_min": 110000,
        "salary_max": 150000,
        "notes": "Отозвал отклик — оффер требовал переезда.",
        "created_days_ago": 25,
    },
]


def main() -> None:
    with SessionLocal() as db:
        user = get_user_by_email(db, DEMO_EMAIL)
        if user is None:
            user = create_user(
                db,
                email=DEMO_EMAIL,
                hashed_password=hash_password(DEMO_PASSWORD),
                full_name="Демо-пользователь",
            )
            print(f"Создан демо-пользователь: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        else:
            print(f"Демо-пользователь уже есть: {DEMO_EMAIL}")

        existing = db.execute(
            select(Application).where(Application.owner_id == user.id)
        ).scalars().all()
        if existing:
            print(f"Откликов уже {len(existing)} — заполнять нечего.")
            return

        now = datetime.now(UTC)

        for sample in SAMPLES:
            payload = ApplicationCreate(
                company=sample["company"],
                role=sample["role"],
                location=sample["location"],
                source=sample["source"],
                priority=sample["priority"],
                stage=sample["stage"],
                salary_min=sample["salary_min"],
                salary_max=sample["salary_max"],
                notes=sample["notes"],
            )
            application = Application(owner_id=user.id, **payload.model_dump())
            application.created_at = now - timedelta(days=sample["created_days_ago"])
            db.add(application)
            db.flush()

            # Правдоподобная история: создан, затем двигался по воронке.
            history = [Stage.APPLIED]
            target = sample["stage"]
            if target in (Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER):
                history.append(Stage.SCREENING)
            if target in (Stage.INTERVIEW, Stage.OFFER):
                history.append(Stage.INTERVIEW)
            if target is Stage.OFFER:
                history.append(Stage.OFFER)
            if target in (Stage.REJECTED, Stage.WITHDRAWN):
                history = [Stage.APPLIED, Stage.SCREENING, target]

            previous = None
            for index, stage in enumerate(history):
                db.add(
                    ApplicationEvent(
                        application_id=application.id,
                        from_stage=previous,
                        to_stage=stage,
                        note="История из демо-данных",
                        created_at=now
                        - timedelta(days=sample["created_days_ago"] - index * 2),
                    )
                )
                previous = stage

        db.commit()
        print(f"Создано откликов: {len(SAMPLES)} для {DEMO_EMAIL}")


if __name__ == "__main__":
    main()
