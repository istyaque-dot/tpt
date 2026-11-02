"""Database access (Supabase Postgres via psycopg2)."""
from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st


@st.cache_resource(show_spinner=False)
def _pool():
    return psycopg2.pool.ThreadedConnectionPool(1, 5, dsn=st.secrets["DB_URL"],
                                                connect_timeout=10)


@contextmanager
def tx():
    """One database transaction. Commits on success, rolls back on any error.

    No 'select 1' ping before every query (that doubled the wait on each screen); a connection that the
    Supabase pooler has dropped is detected on first use, replaced and the statement run again once."""
    pool = _pool()
    conn = pool.getconn()
    if conn.closed:
        pool.putconn(conn, close=True)
        conn = pool.getconn()
    rc = None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            rc = _RetryCursor(cur, conn)
            yield rc
        rc.conn.commit()
        if rc.wrote:
            # something was saved -> every cached read is out of date
            st.cache_data.clear()
    except Exception:
        try:
            (rc.conn if rc else conn).rollback()
        except Exception:
            pass
        raise
    finally:
        if rc is not None and rc.conn is not conn:      # replaced connection: close the extra one
            try:
                rc.conn.close()
            except Exception:
                pass
        try:
            pool.putconn(conn, close=bool(conn.closed) or (rc is not None and rc.conn is not conn))
        except Exception:
            pass


class _RetryCursor:
    """Runs statements; if the FIRST one fails because the pooled connection was dead, reconnects once."""

    def __init__(self, cur, conn):
        self._cur, self.conn, self._first, self.wrote = cur, conn, True, False

    def execute(self, sql, params=None):
        if not self.wrote and sql.lstrip()[:6].lower() in ("insert", "update", "delete"):
            self.wrote = True
        try:
            self._cur.execute(sql, params)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if not self._first:
                raise
            self.conn = psycopg2.connect(st.secrets["DB_URL"], connect_timeout=10)
            self._cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            self._cur.execute(sql, params)
        self._first = False

    def __getattr__(self, name):
        return getattr(self._cur, name)


def query(sql: str, params=None) -> list[dict]:
    """Read rows. Results are kept in memory until anything is saved (or 5 minutes pass),
    so moving between screens and typing in forms does not wait for the database again."""
    return _cached_query(sql, params)


@st.cache_data(ttl=300, show_spinner=False, max_entries=1000)
def _cached_query(sql: str, params) -> list[dict]:
    return _query_now(sql, params)


def _query_now(sql: str, params=None) -> list[dict]:
    with tx() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def one(sql: str, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=None):
    with tx() as cur:
        cur.execute(sql, params)
        if cur.description:
            r = cur.fetchone()
            return dict(r) if r else None
        return None


def df(sql: str, params=None) -> pd.DataFrame:
    return pd.DataFrame(query(sql, params))


# ---------- Settings ----------

@st.cache_data(ttl=60, show_spinner=False)
def get_settings() -> dict:
    return {r["key"]: r["value"] for r in query("select key, value from settings")}


def setting(key: str, default=None):
    return get_settings().get(key, default)


def setting_bool(key: str) -> bool:
    return str(setting(key, "false")).lower() == "true"


def save_setting(key: str, value):
    execute("insert into settings(key, value) values (%s, %s) "
            "on conflict (key) do update set value = excluded.value", (key, str(value)))
    get_settings.clear()


# ---------- Accounts ----------

@st.cache_data(ttl=30, show_spinner=False)
def system_accounts() -> dict:
    return {r["system_code"]: r["id"] for r in
            query("select system_code, id from accounts where system_code is not null")}


def accounts(acc_types, active_only=True) -> list[dict]:
    if isinstance(acc_types, str):
        acc_types = [acc_types]
    sql = "select * from accounts where acc_type = any(%s)"
    if active_only:
        sql += " and active"
    return query(sql + " order by acc_type, name", (list(acc_types),))


def money_accounts() -> list[dict]:
    """Cash + Bank accounts, Cash first."""
    return accounts(["CASH", "BANK"])


def lookups(kind: str) -> list[str]:
    return [r["name"] for r in query("select name from lookups where kind=%s order by name", (kind,))]


def add_lookup(cur, kind: str, name: str):
    name = (name or "").strip()
    if name:
        cur.execute("insert into lookups(kind, name) values (%s, %s) on conflict do nothing",
                    (kind, name))


def clear_caches():
    st.cache_data.clear()
