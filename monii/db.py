"""Persistent storage. SQLite locally, PostgreSQL in production."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE,
 name TEXT NOT NULL, password_hash TEXT, external_key TEXT UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
 email TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, entity TEXT NOT NULL, currency TEXT NOT NULL,
 opening_minor BIGINT NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 UNIQUE(user_id, entity, name)
);
CREATE TABLE IF NOT EXISTS budgets (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 entity TEXT NOT NULL, currency TEXT NOT NULL, month TEXT NOT NULL,
 category TEXT NOT NULL, amount_minor BIGINT NOT NULL CHECK(amount_minor > 0),
 UNIQUE(user_id, entity, currency, month, category)
);
CREATE TABLE IF NOT EXISTS goals (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 entity TEXT NOT NULL, currency TEXT NOT NULL, name TEXT NOT NULL,
 target_minor BIGINT NOT NULL CHECK(target_minor > 0),
 saved_minor BIGINT NOT NULL DEFAULT 0 CHECK(saved_minor >= 0), deadline TEXT,
 version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS schedules (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 account_id INTEGER NOT NULL REFERENCES accounts(id), kind TEXT NOT NULL,
 amount_minor BIGINT NOT NULL CHECK(amount_minor > 0), category TEXT NOT NULL,
 note TEXT NOT NULL, next_due TEXT NOT NULL, cadence TEXT NOT NULL,
 anchor_day INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS obligations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 entity TEXT NOT NULL, currency TEXT NOT NULL, direction TEXT NOT NULL,
 name TEXT NOT NULL, total_minor BIGINT NOT NULL CHECK(total_minor > 0), due TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 account_id INTEGER NOT NULL REFERENCES accounts(id),
 destination_id INTEGER REFERENCES accounts(id), kind TEXT NOT NULL,
 amount_minor BIGINT NOT NULL CHECK(amount_minor > 0), destination_minor BIGINT,
 date TEXT NOT NULL, category TEXT NOT NULL, note TEXT NOT NULL,
 schedule_id INTEGER REFERENCES schedules(id), occurrence TEXT,
 obligation_id INTEGER REFERENCES obligations(id),
 created_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(user_id, schedule_id, occurrence)
);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, date);
CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules(user_id);
"""


class Database:
    def __init__(self, location=None):
        default = Path(__file__).resolve().parents[1] / "data" / "monii.db"
        self.location = str(location or os.getenv("DATABASE_URL") or default)
        self.postgres = self.location.startswith(("postgres://", "postgresql://"))
        if not self.postgres:
            Path(self.location).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            schema = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY") if self.postgres else SCHEMA
            for statement in schema.split(";"):
                if statement.strip():
                    conn.execute(statement)

    @contextmanager
    def connect(self, write=False):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            raw = psycopg.connect(self.location, row_factory=dict_row, connect_timeout=10)
        else:
            raw = sqlite3.connect(self.location, timeout=15)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys=ON")
            raw.execute("PRAGMA journal_mode=WAL")
            if write:
                raw.execute("BEGIN IMMEDIATE")
        try:
            yield Connection(raw, self.postgres)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()


class Connection:
    def __init__(self, raw, postgres):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, params=()):
        return self.raw.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def rows(self, sql, params=()):
        return [dict(row) for row in self.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        row = self.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def insert(self, table, values):
        # Table and column names are always internal constants, never user input.
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        return self.one(f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING id", tuple(values.values()))["id"]
