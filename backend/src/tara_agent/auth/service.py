"""密码验证和不透明登录会话的业务逻辑。"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tara_agent.persistence.database import Database
from tara_agent.persistence.models import AuthSession, User


class EmailAlreadyRegisteredError(ValueError):
    """邮箱已经存在。"""


class InvalidCredentialsError(ValueError):
    """登录凭据不正确。"""


class GuestAccountConflictError(RuntimeError):
    """配置的游客邮箱已经被普通账户占用。"""


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """通过认证后传递给 API 的最小用户身份。"""

    id: str
    email: str
    display_name: str
    is_guest: bool


@dataclass(frozen=True, slots=True)
class IssuedLogin:
    """仅在登录响应中短暂存在的原始会话令牌。"""

    user: CurrentUser
    token: str
    expires_at: datetime


class AuthService:
    """使用 Argon2 密码哈希和服务端令牌哈希管理身份。"""

    def __init__(
        self,
        database: Database,
        *,
        session_days: int,
        guest_email: str,
        guest_display_name: str,
    ) -> None:
        self.database = database
        self.session_days = session_days
        self.guest_email = guest_email.strip().lower()
        self.guest_display_name = guest_display_name.strip()
        self.password_hash = PasswordHash.recommended()
        self._dummy_hash = self.password_hash.hash("tara-agent-invalid-password")

    async def register(self, *, email: str, display_name: str, password: str) -> IssuedLogin:
        normalized_email = email.strip().lower()
        password_hash = await asyncio.to_thread(self.password_hash.hash, password)
        user = User(
            email=normalized_email,
            display_name=display_name.strip(),
            password_hash=password_hash,
        )
        try:
            async with self.database.session() as session:
                session.add(user)
        except IntegrityError as error:
            raise EmailAlreadyRegisteredError(normalized_email) from error
        return await self._issue_login(user)

    async def login_guest(self) -> IssuedLogin:
        """取得所有开发访客共享的同一个用户身份。"""

        async with self.database.session() as session:
            user = await session.scalar(select(User).where(User.email == self.guest_email))

        if user is None:
            password_hash = await asyncio.to_thread(
                self.password_hash.hash,
                secrets.token_urlsafe(48),
            )
            user = User(
                email=self.guest_email,
                display_name=self.guest_display_name,
                password_hash=password_hash,
                is_guest=True,
            )
            try:
                async with self.database.session() as session:
                    session.add(user)
            except IntegrityError:
                async with self.database.session() as session:
                    user = await session.scalar(
                        select(User).where(User.email == self.guest_email)
                    )

        if user is None or not user.is_guest:
            raise GuestAccountConflictError(self.guest_email)
        if user.status != "active":
            raise InvalidCredentialsError
        return await self._issue_login(user)

    async def login(self, *, email: str, password: str) -> IssuedLogin:
        normalized_email = email.strip().lower()
        async with self.database.session() as session:
            user = await session.scalar(select(User).where(User.email == normalized_email))

        stored_hash = user.password_hash if user is not None else self._dummy_hash
        try:
            valid, updated_hash = await asyncio.to_thread(
                self.password_hash.verify_and_update,
                password,
                stored_hash,
            )
        except PwdlibError:
            valid, updated_hash = False, None
        if not valid or user is None or user.status != "active":
            raise InvalidCredentialsError

        now = datetime.now(UTC)
        async with self.database.session() as session:
            persisted_user = await session.get(User, user.id, with_for_update=True)
            if persisted_user is None or persisted_user.status != "active":
                raise InvalidCredentialsError
            if updated_hash:
                persisted_user.password_hash = updated_hash
            persisted_user.last_login_at = now
        return await self._issue_login(user)

    async def authenticate(self, token: str | None) -> CurrentUser | None:
        if not token:
            return None
        now = datetime.now(UTC)
        token_hash = _token_hash(token)
        async with self.database.session() as session:
            row = await session.execute(
                select(User)
                .join(AuthSession, AuthSession.user_id == User.id)
                .where(
                    AuthSession.token_hash == token_hash,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now,
                    User.status == "active",
                )
            )
            user = row.scalar_one_or_none()
        return _current_user(user) if user is not None else None

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        now = datetime.now(UTC)
        async with self.database.session() as session:
            auth_session = await session.scalar(
                select(AuthSession)
                .where(AuthSession.token_hash == _token_hash(token))
                .with_for_update()
            )
            if auth_session is not None and auth_session.revoked_at is None:
                auth_session.revoked_at = now

    async def _issue_login(self, user: User) -> IssuedLogin:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=self.session_days)
        async with self.database.session() as session:
            session.add(
                AuthSession(
                    user_id=user.id,
                    token_hash=_token_hash(token),
                    expires_at=expires_at,
                    last_seen_at=now,
                )
            )
        return IssuedLogin(user=_current_user(user), token=token, expires_at=expires_at)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _current_user(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_guest=user.is_guest,
    )
