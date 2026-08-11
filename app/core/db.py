import pymysql
import pymysql.cursors
from contextlib import contextmanager
from app.config import settings
import logging

logger = logging.getLogger("cobranca.db")

def get_connection():
    return pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=True,
    )

@contextmanager
def db():
    conn = None
    try:
        conn = get_connection()
        yield conn
    except pymysql.MySQLError as e:
        logger.error(f"DB error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def query(sql: str, params=None) -> list:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

def query_one(sql: str, params=None):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()

def execute(sql: str, params=None) -> int:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.lastrowid
