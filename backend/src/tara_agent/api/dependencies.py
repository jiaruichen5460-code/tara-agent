"""跨路由复用的身份和请求安全依赖。"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from tara_agent.auth import AuthService, CurrentUser


async def require_current_user(request: Request) -> CurrentUser:
    """从 HttpOnly Cookie 解析当前用户，拒绝匿名访问。"""

    service: AuthService | None = request.app.state.auth_service
    if service is None:
        if request.app.state.settings.environment == "test":
            return CurrentUser(
                id="test-user",
                email="test@example.com",
                display_name="测试用户",
                is_guest=False,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务不可用。",
        )
    cookie_name = request.app.state.settings.auth_cookie_name
    user = await service.authenticate(request.cookies.get(cookie_name))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录。",
        )
    validate_request_origin(request)
    return user


def validate_request_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin and origin not in request.app.state.settings.cors_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="请求来源不受信任。",
        )


CurrentUserDependency = Annotated[CurrentUser, Depends(require_current_user)]
