"""为共享游客账户增加明确标识。

修订版本：20260918_04
前置版本：20260917_03
创建时间：2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_04"
down_revision: str | Sequence[str] | None = "20260917_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """标记普通账户和共享游客账户。"""

    op.add_column(
        "users",
        sa.Column("is_guest", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    """移除游客账户标识。"""

    op.drop_column("users", "is_guest")
