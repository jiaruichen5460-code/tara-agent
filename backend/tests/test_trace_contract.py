from tara_agent.observability.contracts import (
    REDACTED_VALUE,
    TraceDataLimits,
    sanitize_trace_mapping,
    sanitize_trace_text,
)


def test_trace_mapping_redacts_credentials_at_any_depth() -> None:
    sanitized = sanitize_trace_mapping(
        {
            "headers": {
                "Authorization": "Bearer private-token",
                "X-API-Key": "private-key",
            },
            "model": {"input_tokens": 120, "max_tokens": 500},
            "message": "password=private-password",
        }
    )

    assert sanitized == {
        "headers": {
            "Authorization": REDACTED_VALUE,
            "X-API-Key": REDACTED_VALUE,
        },
        "model": {"input_tokens": 120, "max_tokens": 500},
        "message": "password=[REDACTED]",
    }


def test_trace_mapping_records_when_values_are_truncated() -> None:
    limits = TraceDataLimits(
        max_depth=2,
        max_collection_items=2,
        max_string_characters=5,
        max_total_values=20,
        max_total_characters=20,
    )
    sanitized = sanitize_trace_mapping(
        {
            "items": ["first", "second", "third"],
            "nested": {"child": {"value": "hidden"}},
            "extra": True,
        },
        limits=limits,
    )

    assert sanitized is not None
    assert sanitized["items"][-1] == {"_trace_truncated": {"omitted_items": 1}}
    assert sanitized["nested"]["child"] == "[TRUNCATED DEPTH LIMIT]"
    assert sanitized["_trace_truncated"] == {"omitted_items": 1}


def test_trace_text_redacts_common_inline_credentials() -> None:
    sanitized = sanitize_trace_text(
        "Bearer abc123 at postgresql://user:password@localhost/db; api_key=secret-value"
    )

    assert sanitized == (
        "Bearer [REDACTED] at postgresql://[REDACTED]@localhost/db; "
        "api_key=[REDACTED]"
    )
