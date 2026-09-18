"""应用配置及适用于当前仓库的默认路径。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_FILE = Path(__file__).resolve()
BACKEND_ROOT = PACKAGE_FILE.parents[2]
PROJECT_ROOT = PACKAGE_FILE.parents[3]


class Settings(BaseSettings):
    """从环境变量或 `backend/.env` 加载运行时设置。"""

    model_config = SettingsConfigDict(
        env_prefix="TARA_",
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Tara Agent API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    dataset_dir: Path = PROJECT_ROOT / "Tara_4_Core_Datasets"
    processed_data_dir: Path = BACKEND_ROOT / "data" / "processed"
    cors_origins: list[str] = ["http://localhost:3000"]
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "TARA_DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_reasoning_effort: Literal["low", "high", "max"] = "low"
    deepseek_timeout_seconds: float = Field(default=60, gt=0, le=300)
    database_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "TARA_DATABASE_URL"),
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=30, gt=0, le=300)
    auth_session_days: int = Field(default=7, ge=1, le=90)
    auth_cookie_name: str = "tara_session"
    auth_guest_login_enabled: bool = True
    auth_guest_email: str = "guest@tara-agent.local"
    auth_guest_display_name: str = "游客共享空间"

    @field_validator("dataset_dir", "processed_data_dir", mode="before")
    @classmethod
    def resolve_project_path(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.resolve(strict=False)

    @field_validator("api_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        normalized = f"/{value.strip('/')}"
        if normalized == "/":
            raise ValueError("api_prefix must not be empty")
        return normalized

    @model_validator(mode="after")
    def keep_generated_data_outside_source_data(self) -> "Settings":
        try:
            self.processed_data_dir.relative_to(self.dataset_dir)
        except ValueError:
            return self
        raise ValueError("processed_data_dir must not be inside dataset_dir")

    def get_database_url(self) -> str:
        """返回适用于 SQLAlchemy 异步引擎的数据库连接地址。"""

        if self.database_url is None:
            raise ValueError("未配置 DATABASE_URL 或 TARA_DATABASE_URL")

        url = self.database_url.get_secret_value()
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql+asyncpg://"):
            return url
        raise ValueError("数据库连接地址必须使用 postgresql:// 或 postgresql+asyncpg://")

    @property
    def auth_cookie_secure(self) -> bool:
        """生产环境只允许通过 HTTPS 发送登录 Cookie。"""

        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """每个进程返回一个按约定保持不变的配置实例。"""

    return Settings()
