"""Регистрация, вход и «кто я»."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.config import get_settings
from app.crud import create_user, get_user_by_email
from app.deps import CurrentUser, DbSession
from app.logging_config import pseudonymise_email
from app.schemas import TokenWithUser, UserCreate, UserRead
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать аккаунт",
)
def register(payload: UserCreate, db: DbSession) -> UserRead:
    """Зарегистрировать нового пользователя.

    Почта сохраняется в нижнем регистре и сравнивается без учёта регистра,
    поэтому `Alice@x.com` и `alice@x.com` — один и тот же аккаунт.
    """
    if get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с такой почтой уже есть",
        )

    user = create_user(
        db,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    logger.info(
        "Аккаунт зарегистрирован",
        extra={"event": "auth.registered", "user_id": str(user.id)},
    )
    return UserRead.model_validate(user)


@router.post(
    "/token",
    response_model=TokenWithUser,
    summary="Войти и получить access-токен",
)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> TokenWithUser:
    """Обменять учётные данные на JWT.

    Используется OAuth2 password flow, чтобы в Swagger UI рабочая кнопка
    «Authorize» и токен можно было вставить в любой OAuth2-клиент.
    """
    user = get_user_by_email(db, form.username)
    # Одинаковое сообщение для «нет такого пользователя» и «неверный пароль»,
    # чтобы по эндпоинту нельзя было выяснить, какие почты зарегистрированы.
    if user is None or not verify_password(form.password, user.hashed_password):
        # Почта в лог не пишется: неудачная попытка входа — тоже персональные
        # данные. Усечённого хеша достаточно, чтобы заметить перебор по одному
        # адресу, не записывая сам адрес.
        logger.warning(
            "Не удалось войти",
            extra={
                "event": "auth.login_failed",
                "email_hash": pseudonymise_email(form.username),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверная почта или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=str(user.id))
    logger.info(
        "Вход выполнен",
        extra={"event": "auth.login", "user_id": str(user.id)},
    )
    return TokenWithUser(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead, summary="Текущий пользователь")
def read_me(current_user: CurrentUser) -> UserRead:
    """Вернуть авторизованного пользователя."""
    return UserRead.model_validate(current_user)
