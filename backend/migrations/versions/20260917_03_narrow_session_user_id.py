"""统一对话所有者与用户主键长度。

修订版本：20260917_03
前置版本：20260917_02
创建时间：2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_03"
down_revision: str | Sequence[str] | None = "20260917_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """把既有所有者字段收窄为 UUID 文本长度。"""

    op.alter_column(
        "chat_sessions",
        "user_id",
        existing_type=sa.String(length=255),
        type_=sa.String(length=36),
        existing_nullable=True,
    )


def downgrade() -> None:
    """恢复首版所有者字段长度。"""

    op.alter_column(
        "chat_sessions",
        "user_id",
        existing_type=sa.String(length=36),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
