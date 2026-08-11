import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'cobranca_local.db')

@contextmanager
def db_local():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def local_query(sql: str, params=()) -> list:
    with db_local() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def local_query_one(sql: str, params=()):
    with db_local() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

def local_execute(sql: str, params=()) -> int:
    with db_local() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid
