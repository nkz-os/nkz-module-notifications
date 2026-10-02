"""Conexión PostgreSQL (sync) al esquema notifications.*.

Solo metadata operativa (canales, entregas, cola de digest) — NUNCA telemetría.
"""
import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import require_postgres_url


def get_conn():
    return psycopg2.connect(require_postgres_url(), cursor_factory=RealDictCursor)
