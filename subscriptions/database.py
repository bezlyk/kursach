import sqlite3
from contextlib import contextmanager
from dataclasses import astuple
from datetime import date
from pathlib import Path

from subscriptions.domain import Payment, StorageError, Subscription, ValidationError


SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    service TEXT NOT NULL CHECK(length(trim(service)) BETWEEN 1 AND 100),
    plan TEXT NOT NULL DEFAULT '' CHECK(length(plan) <= 100),
    category TEXT NOT NULL DEFAULT '' CHECK(length(category) <= 50),
    note TEXT NOT NULL DEFAULT '' CHECK(length(note) <= 500),
    amount_cents INTEGER NOT NULL
        CHECK(typeof(amount_cents) = 'integer' AND amount_cents BETWEEN 1 AND 9999999),
    period TEXT NOT NULL CHECK(period IN ('month', 'year')),
    next_date TEXT NOT NULL CHECK(length(next_date) = 10
        AND date(next_date, '+0 days') IS NOT NULL AND date(next_date, '+0 days') = next_date),
    active INTEGER NOT NULL CHECK(active IN (0, 1)),
    anchor_date TEXT NOT NULL CHECK(length(anchor_date) = 10
        AND date(anchor_date, '+0 days') IS NOT NULL AND date(anchor_date, '+0 days') = anchor_date)
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE RESTRICT,
    planned_date TEXT NOT NULL CHECK(length(planned_date) = 10
        AND date(planned_date, '+0 days') IS NOT NULL AND date(planned_date, '+0 days') = planned_date),
    actual_date TEXT NOT NULL CHECK(length(actual_date) = 10
        AND date(actual_date, '+0 days') IS NOT NULL AND date(actual_date, '+0 days') = actual_date),
    amount_cents INTEGER NOT NULL
        CHECK(typeof(amount_cents) = 'integer' AND amount_cents BETWEEN 1 AND 9999999),
    UNIQUE(subscription_id, planned_date)
);
CREATE INDEX IF NOT EXISTS payments_actual_date ON payments(actual_date);
CREATE INDEX IF NOT EXISTS subscriptions_next_date ON subscriptions(active, next_date);
CREATE TRIGGER IF NOT EXISTS active_limit_insert
BEFORE INSERT ON subscriptions
WHEN NEW.active = 1 AND (SELECT count(*) FROM subscriptions WHERE active = 1) >= 5
BEGIN
    SELECT RAISE(ABORT, 'active_limit');
END;
CREATE TRIGGER IF NOT EXISTS active_limit_update
BEFORE UPDATE OF active ON subscriptions
WHEN NEW.active = 1 AND OLD.active = 0
    AND (SELECT count(*) FROM subscriptions WHERE active = 1) >= 5
BEGIN
    SELECT RAISE(ABORT, 'active_limit');
END;
"""


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys = ON")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise StorageError("Версия базы не поддерживается. Используйте подходящую версию программы.")
            self.connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version = 1;\nCOMMIT;")
        except BaseException:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    @contextmanager
    def transaction(self):
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def list_subscriptions(self):
        rows = self.connection.execute(
            "SELECT * FROM subscriptions ORDER BY active DESC, next_date, id"
        ).fetchall()
        return [self._subscription(row) for row in rows]

    def get_subscription(self, subscription_id):
        row = self.connection.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
        ).fetchone()
        if row is None:
            raise ValidationError("Подписка не найдена. Обновите список.")
        return self._subscription(row)

    def active_count(self):
        return self.connection.execute("SELECT count(*) FROM subscriptions WHERE active = 1").fetchone()[0]

    def insert_subscription(self, data):
        cursor = self.connection.execute(
            """INSERT INTO subscriptions
            (service, plan, category, note, amount_cents, period, next_date, active, anchor_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", self._values(data)
        )
        return cursor.lastrowid

    def update_subscription(self, subscription_id, data):
        self.connection.execute(
            """UPDATE subscriptions SET service = ?, plan = ?, category = ?, note = ?,
            amount_cents = ?, period = ?, next_date = ?, active = ?, anchor_date = ? WHERE id = ?""",
            (*self._values(data), subscription_id),
        )

    def update_next_date(self, subscription_id, next_date):
        self.connection.execute(
            "UPDATE subscriptions SET next_date = ? WHERE id = ?",
            (next_date.isoformat(), subscription_id),
        )

    def insert_payment(self, subscription_id, planned_date, actual_date, amount_cents):
        cursor = self.connection.execute(
            """INSERT INTO payments (subscription_id, planned_date, actual_date, amount_cents)
            VALUES (?, ?, ?, ?)""",
            (subscription_id, planned_date.isoformat(), actual_date.isoformat(), amount_cents),
        )
        return cursor.lastrowid

    def has_payments(self, subscription_id):
        return self.connection.execute(
            "SELECT 1 FROM payments WHERE subscription_id = ? LIMIT 1", (subscription_id,)
        ).fetchone() is not None

    def delete_subscription(self, subscription_id):
        self.connection.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))

    def list_payments(self, subscription_id=None, month=None):
        query = """SELECT p.*, s.service FROM payments p
        JOIN subscriptions s ON s.id = p.subscription_id"""
        clauses, params = [], []
        if subscription_id is not None:
            clauses.append("p.subscription_id = ?")
            params.append(subscription_id)
        if month is not None:
            clauses.append("substr(p.actual_date, 1, 7) = ?")
            params.append(month)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY p.actual_date DESC, p.id DESC"
        return [Payment(
            row["id"], row["subscription_id"], row["service"],
            date.fromisoformat(row["planned_date"]), date.fromisoformat(row["actual_date"]),
            row["amount_cents"],
        ) for row in self.connection.execute(query, params)]

    @staticmethod
    def _values(data):
        values = list(astuple(data))
        values[6] = data.next_date.isoformat()
        values[7] = int(data.active)
        values[8] = data.anchor_date.isoformat()
        return tuple(values)

    @staticmethod
    def _subscription(row):
        return Subscription(
            row["id"], row["service"], row["plan"], row["category"], row["note"],
            row["amount_cents"], row["period"], date.fromisoformat(row["next_date"]),
            bool(row["active"]), date.fromisoformat(row["anchor_date"]),
        )
