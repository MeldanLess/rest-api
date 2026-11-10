"""Общие зависимости FastAPI.

Псевдонимы `Annotated` делают сигнатуры маршрутов короткими, а граф зависимостей
наглядным.
"""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

DbSession = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Не удалось проверить учётные данные",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: TokenDep, db: DbSession) -> User:
    """Превращает bearer-токен в пользователя или поднимает 401."""
    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if not subject:
            raise CREDENTIALS_EXCEPTION
        user_id = uuid.UUID(subject)
    except (jwt.PyJWTError, ValueError):
        # `from None` — нам не нужно, чтобы в лог утекло, какой именно токен
        # не прошёл проверку; наружу идёт ровно один понятный 401.
        raise CREDENTIALS_EXCEPTION from None

    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_EXCEPTION
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
