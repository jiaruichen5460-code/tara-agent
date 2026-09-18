"""创建会话、消息与 Agent 链路追踪表。

修订版本：20260917_01
前置版本：无
创建时间：2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_ARRAY = sa.text("'[]'::jsonb")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    """创建首版持久化结构。"""

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_chat_sessions"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index(
        "ix_chat_sessions_user_status_updated",
        "chat_sessions",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "agent_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_trace_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("workflow_name", sa.String(length=120), nullable=False),
        sa.Column("workflow_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("model_provider", sa.String(length=80), nullable=True),
        sa.Column("model_name", sa.String(length=160), nullable=True),
        sa.Column(
            "model_parameters",
            postgresql.JSONB(),
            server_default=EMPTY_OBJECT,
            nullable=False,
        ),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_data", postgresql.JSONB(), nullable=True),
        sa.Column("data_sources", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("markers", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("attributes", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_traces_duration_nonnegative",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_agent_traces_retry_count_nonnegative"),
        sa.CheckConstraint(
            "sample_count IS NULL OR sample_count >= 0",
            name="ck_agent_traces_sample_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["parent_trace_id"],
            ["agent_traces.id"],
            name="fk_agent_traces_parent_trace_id_agent_traces",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name="fk_agent_traces_session_id_chat_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_traces"),
    )
    op.create_index("ix_agent_traces_correlation_id", "agent_traces", ["correlation_id"])
    op.create_index("ix_agent_traces_model_name", "agent_traces", ["model_name"])
    op.create_index("ix_agent_traces_parent_trace_id", "agent_traces", ["parent_trace_id"])
    op.create_index("ix_agent_traces_session_id", "agent_traces", ["session_id"])
    op.create_index(
        "ix_agent_traces_session_started", "agent_traces", ["session_id", "started_at"]
    )
    op.create_index(
        "ix_agent_traces_status_started", "agent_traces", ["status", "started_at"]
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("parent_message_id", sa.Uuid(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("message_type", sa.String(length=32), server_default="text", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="completed", nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("content_parts", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("sequence_no >= 0", name="ck_chat_messages_sequence_nonnegative"),
        sa.ForeignKeyConstraint(
            ["parent_message_id"],
            ["chat_messages.id"],
            name="fk_chat_messages_parent_message_id_chat_messages",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name="fk_chat_messages_session_id_chat_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["agent_traces.id"],
            name="fk_chat_messages_trace_id_agent_traces",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        sa.UniqueConstraint(
            "session_id", "sequence_no", name="uq_chat_messages_session_sequence"
        ),
    )
    op.create_index("ix_chat_messages_parent_message_id", "chat_messages", ["parent_message_id"])
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index(
        "ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"]
    )
    op.create_index("ix_chat_messages_trace_id", "chat_messages", ["trace_id"])
    op.create_index(
        "ix_chat_messages_trace_created", "chat_messages", ["trace_id", "created_at"]
    )

    op.create_table(
        "trace_spans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_span_id", sa.Uuid(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("span_kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_data", postgresql.JSONB(), nullable=True),
        sa.Column("model_provider", sa.String(length=80), nullable=True),
        sa.Column("model_name", sa.String(length=160), nullable=True),
        sa.Column(
            "model_parameters",
            postgresql.JSONB(),
            server_default=EMPTY_OBJECT,
            nullable=False,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("tool_name", sa.String(length=160), nullable=True),
        sa.Column("filters", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column("marker", sa.String(length=16), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("sample_ids", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("data_sources", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("artifact_refs", postgresql.JSONB(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("attributes", postgresql.JSONB(), server_default=EMPTY_OBJECT, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("sequence_no >= 0", name="ck_trace_spans_sequence_nonnegative"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_trace_spans_duration_nonnegative",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_trace_spans_retry_count_nonnegative"),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_trace_spans_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_trace_spans_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_trace_spans_total_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "context_length IS NULL OR context_length >= 0",
            name="ck_trace_spans_context_length_nonnegative",
        ),
        sa.CheckConstraint(
            "sample_count IS NULL OR sample_count >= 0",
            name="ck_trace_spans_sample_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["parent_span_id"],
            ["trace_spans.id"],
            name="fk_trace_spans_parent_span_id_trace_spans",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["agent_traces.id"],
            name="fk_trace_spans_trace_id_agent_traces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_trace_spans"),
        sa.UniqueConstraint("trace_id", "sequence_no", name="uq_trace_spans_trace_sequence"),
    )
    op.create_index("ix_trace_spans_parent_span_id", "trace_spans", ["parent_span_id"])
    op.create_index("ix_trace_spans_trace_id", "trace_spans", ["trace_id"])
    op.create_index(
        "ix_trace_spans_trace_started", "trace_spans", ["trace_id", "started_at"]
    )
    op.create_index(
        "ix_trace_spans_kind_status", "trace_spans", ["span_kind", "status"]
    )
    op.create_index(
        "ix_trace_spans_tool_started", "trace_spans", ["tool_name", "started_at"]
    )
    op.create_index(
        "ix_trace_spans_model_started", "trace_spans", ["model_name", "started_at"]
    )


def downgrade() -> None:
    """按依赖关系逆序删除首版持久化结构。"""

    op.drop_table("trace_spans")
    op.drop_table("chat_messages")
    op.drop_table("agent_traces")
    op.drop_table("chat_sessions")
