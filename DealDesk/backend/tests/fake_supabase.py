"""A tiny in-memory stand-in for the Supabase client. It supports only what the app uses:
table(name).select().eq().in_().order().limit().execute(), .insert(), .update().eq().execute()."""

import copy
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace


class _Query:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.mode = "select"
        self.filters = []
        self.rows_in = None
        self.payload = None
        self.order_by = None
        self.max_rows = None

    def select(self, *_):
        self.mode = "select"
        return self

    def insert(self, rows):
        self.mode, self.rows_in = "insert", rows if isinstance(rows, list) else [rows]
        return self

    def upsert(self, row):
        self.mode, self.rows_in = "upsert", [row]
        return self

    def update(self, payload):
        self.mode, self.payload = "update", payload
        return self

    def eq(self, column, value):
        self.filters.append(lambda r: r.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda r: r.get(column) in values)
        return self

    def order(self, column):
        self.order_by = column
        return self

    def limit(self, n):
        self.max_rows = n
        return self

    def execute(self):
        table = self.db.tables.setdefault(self.name, [])
        if self.db.fail_next_write and self.mode != "select":
            self.db.fail_next_write = False
            raise RuntimeError("database down")
        if self.mode == "insert":
            out = []
            for r in self.rows_in:
                row = {"id": str(uuid.uuid4()), "created_at": datetime.now(UTC).isoformat(), **copy.deepcopy(r)}
                table.append(row)
                out.append(copy.deepcopy(row))
            self.db.writes.append((self.name, "insert", len(out)))
            return SimpleNamespace(data=out)
        if self.mode == "upsert":
            row = copy.deepcopy(self.rows_in[0])
            old = next((r for r in table if r.get("id") == row.get("id")), None)
            if old is None:
                table.append({"created_at": datetime.now(UTC).isoformat(), **row})
            else:
                old.update(row)
            self.db.writes.append((self.name, "upsert", 1))
            return SimpleNamespace(data=[row])
        rows = [r for r in table if all(f(r) for f in self.filters)]
        if self.mode == "update":
            for r in rows:
                r.update(copy.deepcopy(self.payload))
            self.db.writes.append((self.name, "update", len(rows)))
            return SimpleNamespace(data=copy.deepcopy(rows))
        if self.order_by:
            rows = sorted(rows, key=lambda r: r.get(self.order_by) or "")
        if self.max_rows:
            rows = rows[: self.max_rows]
        return SimpleNamespace(data=copy.deepcopy(rows))


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.writes: list[tuple] = []
        self.fail_next_write = False

    def table(self, name):
        return _Query(self, name)
