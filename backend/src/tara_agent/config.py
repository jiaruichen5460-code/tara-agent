"""Application configuration with repository-safe path defaults."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_FILE = Path(__file__).resolve()
BACKEND_ROOT = PACKAGE_FILE.parents[2]
PROJECT_ROOT = PACKAGE_FILE.parents[3]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or `backend/.env`."""

    model_config = SettingsConfigDict(
        env_prefix="TARA_",
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Tara-Agent API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    dataset_dir: Path = PROJECT_ROOT / "Tara_4_Core_Datasets"
    processed_data_dir: Path = BACKEND_ROOT / "data" / "processed"
    cors_origins: list[str] = ["http://localhost:3000"]

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


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()
