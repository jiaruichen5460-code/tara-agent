"""为会话增加置顶时间。

修订版本：20260918_05
前置版本：20260918_04
创建时间：2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_05"
down_revision: str | Sequence[str] | None = "20260918_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加可为空的置顶时间。"""

    op.add_column(
        "chat_sessions",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """移除置顶时间。"""

    op.drop_column("chat_sessions", "pinned_at")
