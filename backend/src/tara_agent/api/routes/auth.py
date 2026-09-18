"""注册、登录、退出和当前用户接口。"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from tara_agent.api.dependencies import CurrentUserDependency, validate_request_origin
from tara_agent.auth import (
    AuthService,
    CurrentUser,
    EmailAlreadyRegisteredError,
    GuestAccountConflictError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("昵称不能为空")
        return normalized


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    display_name: str
    is_guest: bool


class AuthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: UserResponse
    expires_at: datetime


def _service(request: Request) -> AuthService:
    service: AuthService | None = request.app.state.auth_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务不可用。",
        )
    return service


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, request: Request, response: Response) -> AuthResponse:
    validate_request_origin(request)
    try:
        login = await _service(request).register(
            email=str(payload.email),
            display_name=payload.display_name,
            password=payload.password,
        )
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已经注册。",
        ) from error
    _set_login_cookie(request, response, login.token)
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(user=_user_response(login.user), expires_at=login.expires_at)


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request, response: Response) -> AuthResponse:
    validate_request_origin(request)
    try:
        issued = await _service(request).login(email=str(payload.email), password=payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码不正确。",
        ) from error
    _set_login_cookie(request, response, issued.token)
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(user=_user_response(issued.user), expires_at=issued.expires_at)


@router.post("/guest", response_model=AuthResponse)
async def guest_login(request: Request, response: Response) -> AuthResponse:
    """在非生产环境进入所有访客共享的测试空间。"""

    validate_request_origin(request)
    settings = request.app.state.settings
    if settings.environment == "production" or not settings.auth_guest_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="游客登录未开放。",
        )
    try:
        issued = await _service(request).login_guest()
    except GuestAccountConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="游客账户配置冲突。",
        ) from error
    _set_login_cookie(request, response, issued.token)
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(user=_user_response(issued.user), expires_at=issued.expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    validate_request_origin(request)
    settings = request.app.state.settings
    await _service(request).logout(request.cookies.get(settings.auth_cookie_name))
    response.delete_cookie(
        settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUserDependency) -> UserResponse:
    return _user_response(user)


def _set_login_cookie(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        max_age=settings.auth_session_days * 24 * 60 * 60,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _user_response(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_guest=user.is_guest,
    )
