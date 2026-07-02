from pathlib import Path

from engine.db.pool import pool

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def migrate() -> list[str]:
    """Apply pending numbered migrations from sql/, each in its own transaction."""
    applied: list[str] = []
    with pool().connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    for path in sorted(SQL_DIR.glob("*.sql")):
        with pool().connection() as conn:
            done = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE filename = %s", (path.name,)
            ).fetchone()
            if done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied
