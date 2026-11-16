import logging

from app.log_redact import QueryTokenRedactor, redact_query_tokens

ACCESS_FMT = '%s - "%s %s HTTP/%s" %d'


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, ACCESS_FMT,
        ("10.0.0.1:1234", "GET", path, "1.1", 200), None,
    )


def test_token_value_is_masked_other_params_kept():
    path = "/api/notifications/public/report-preferences?u=user-a&t=acme&lang=es&token=abc123:1799999999"
    assert redact_query_tokens(path) == (
        "/api/notifications/public/report-preferences?u=user-a&t=acme&lang=es&token=***"
    )


def test_token_first_or_middle_param_is_masked():
    assert redact_query_tokens("/x?token=s3cret&lang=es") == "/x?token=***&lang=es"


def test_path_without_token_is_unchanged():
    assert redact_query_tokens("/health") == "/health"
    assert redact_query_tokens("/x?mytoken=keep") == "/x?mytoken=keep"


def test_filter_rewrites_access_record_and_keeps_it():
    record = _access_record("/api/notifications/public/report-preferences?u=a&t=acme&token=deadbeef:1")
    assert QueryTokenRedactor().filter(record) is True
    message = record.getMessage()
    assert "deadbeef" not in message
    assert "token=***" in message


def test_filter_installed_on_uvicorn_access_logger():
    import app.main  # noqa: F401 — importing the app installs the filter

    logger = logging.getLogger("uvicorn.access")
    assert any(isinstance(f, QueryTokenRedactor) for f in logger.filters)
