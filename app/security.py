"""Хеширование паролей и JSON Web Tokens.

bcrypt используется напрямую, а не через `passlib`: `passlib` не поддерживается
с 2020 года, а его бэкенд для bcrypt несовместим с bcrypt 4.x. Вызвать библиотеку
самому — это две строки и на одну зависимость меньше.

Обратите внимание на ограничение в 72 байта, которое накладывает bcrypt: схемы
ограничивают длину, чтобы API отвечал понятным 422, а не падал внутри хеширования
с непонятной ошибкой.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()

#: bcrypt хеширует не больше 72 байт входных данных.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    """Хеширует открытый пароль со свежей случайной солью."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет открытый пароль против сохранённого хеша.

    Возвращает False, а не бросает исключение, если хеш повреждён, чтобы
    испорченная строка в базе не превращалась в 500.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Создаёт подписанный JWT для указанного идентификатора пользователя."""
    now = datetime.now(UTC)
    expires = now + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expires,
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    """Декодирует и проверяет JWT.

    Бросает подклассы `jwt.PyJWTError` при неверной подписи или истёкшем токене;
    вызывающий код превращает это в 401.
    """
    return jwt.decode(
        token, settings.secret_key, algorithms=[settings.algorithm]
    )
