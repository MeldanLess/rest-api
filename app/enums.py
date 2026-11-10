"""Доменный словарь.

Вынесен в отдельный модуль, чтобы ORM-модели, схемы Pydantic и роутеры
говорили об одних и тех же понятиях, не импортируя друг друга.
"""

from enum import StrEnum


class Stage(StrEnum):
    """На каком этапе отбора сейчас находится отклик."""

    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

    @property
    def is_terminal(self) -> bool:
        """Конечные этапы завершают процесс — дальше ничего не происходит."""
        return self in (Stage.OFFER, Stage.REJECTED, Stage.WITHDRAWN)

    @property
    def is_active(self) -> bool:
        """Активные этапы — отклик ещё в игре."""
        return self in (Stage.APPLIED, Stage.SCREENING, Stage.INTERVIEW)


class Source(StrEnum):
    """Где нашли вакансию."""

    HH = "hh"
    LINKEDIN = "linkedin"
    TELEGRAM = "telegram"
    REFERRAL = "referral"
    UNIVERSITY = "university"
    COMPANY_SITE = "company_site"
    OTHER = "other"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: Допустимые переходы между этапами. Движение назад разрешено намеренно:
#: компания может перенести собеседование, и инструмент, который отказывается
#: записывать реальность, хуже, чем его отсутствие.
ALLOWED_TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.APPLIED: {Stage.SCREENING, Stage.INTERVIEW, Stage.REJECTED, Stage.WITHDRAWN},
    Stage.SCREENING: {Stage.INTERVIEW, Stage.REJECTED, Stage.WITHDRAWN, Stage.APPLIED},
    Stage.INTERVIEW: {Stage.OFFER, Stage.REJECTED, Stage.WITHDRAWN, Stage.SCREENING},
    Stage.OFFER: {Stage.WITHDRAWN, Stage.REJECTED},
    Stage.REJECTED: {Stage.APPLIED, Stage.SCREENING},
    Stage.WITHDRAWN: {Stage.APPLIED},
}


def enum_values(enum_class):
    """Научить SQLAlchemy хранить *значения* enum, а не имена его членов.

    Без этого `Stage.APPLIED` сохранилось бы как "APPLIED", пока API говорит
    строчными "applied". Одинаковое написание везде снимает целый класс багов,
    которые потом больно отлаживать.
    """
    return [member.value for member in enum_class]
