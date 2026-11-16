"""Mask secret query values in the server's access log.

Signed links (the weekly-report preferences page) carry their token in the query
string; uvicorn's access log prints the full path. The filter replaces the value of
every ``token`` query parameter with ``***`` and keeps the rest of the line.
"""
import logging
import re

_TOKEN_VALUE = re.compile(r"([?&]token=)[^&#\s]*")


def redact_query_tokens(text: str) -> str:
    return _TOKEN_VALUE.sub(r"\1***", text)


class QueryTokenRedactor(logging.Filter):
    """Rewrites string arguments of a log record; never drops the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_query_tokens(a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = redact_query_tokens(record.msg)
        return True


def install_access_log_redaction() -> None:
    """Idempotent: attaches the filter to uvicorn's access logger once."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QueryTokenRedactor) for f in logger.filters):
        logger.addFilter(QueryTokenRedactor())
