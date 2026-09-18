from pathlib import Path

import pytest
from pydantic import ValidationError

from tara_agent.config import BACKEND_ROOT, PROJECT_ROOT, Settings


def test_default_paths_keep_source_and_generated_data_separate() -> None:
    settings = Settings(_env_file=None)

    assert settings.dataset_dir == PROJECT_ROOT / "Tara_4_Core_Datasets"
    assert settings.processed_data_dir == BACKEND_ROOT / "data" / "processed"
    assert settings.dataset_dir != settings.processed_data_dir


def test_relative_paths_are_resolved_from_backend_root() -> None:
    settings = Settings(
        dataset_dir=Path("../fixtures/source"),
        processed_data_dir=Path("data/generated"),
        _env_file=None,
    )

    assert settings.dataset_dir == (BACKEND_ROOT / "../fixtures/source").resolve()
    assert settings.processed_data_dir == (BACKEND_ROOT / "data/generated").resolve()


def test_generated_data_cannot_be_placed_inside_source_data(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"

    with pytest.raises(ValidationError, match="must not be inside dataset_dir"):
        Settings(
            dataset_dir=source_dir,
            processed_data_dir=source_dir / "generated",
            _env_file=None,
        )


def test_auth_cookie_is_secure_only_in_production() -> None:
    development = Settings(environment="development", _env_file=None)
    production = Settings(environment="production", _env_file=None)

    assert development.auth_cookie_secure is False
    assert production.auth_cookie_secure is True
