import atexit
import os

from psycopg_pool import ConnectionPool

from engine.config import settings

_pool: ConnectionPool | None = None


def db_url() -> str:
    # ENGINE_DB=test routes everything (CLI, tracker, tests) at the test database.
    if os.environ.get("ENGINE_DB") == "test":
        return settings().test_database_url
    return settings().database_url


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # small pool: laptop RAM budget, and this scale needs nothing more
        _pool = ConnectionPool(db_url(), min_size=1, max_size=5, open=True)
        atexit.register(reset_pool)
    return _pool


def reset_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = None
