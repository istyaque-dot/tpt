"""Database access (Supabase Postgres via psycopg2)."""
from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st


def _db_args() -> dict:
    """Connection settings from Streamlit Secrets.

    Preferred (no URL mistakes possible, any password works):
        [database]
        host = "aws-0-eu-west-1.pooler.supabase.com"
        port = 6543
        user = "postgres.<project-code>"
        password = "..."
        dbname = "postgres"
    Old style DB_URL = "postgresql://..." still works."""
    d = st.secrets.get("database")
    if d:
        missing = [k for k in ("host", "user", "password") if not str(d.get(k, "")).strip()]
        if missing:
            _stop_with_help(f"Secrets ke [database] mein ye khaali hai: {', '.join(missing)}.")
        return {"host": str(d["host"]).strip(), "port": int(d.get("port", 6543)),
                "user": str(d["user"]).strip(), "password": str(d["password"]),
                "dbname": str(d.get("dbname", "postgres")).strip(), "sslmode": "require",
                "connect_timeout": 10}
    url = str(st.secrets.get("DB_URL", "")).strip()
    if not url:
        _stop_with_help("Streamlit Secrets mein [database] (ya DB_URL) nahi mila.")
    return {"dsn": url, "connect_timeout": 10}


def _password() -> str:
    d = st.secrets.get("database")
    if d:
        return str(d.get("password", ""))
    try:
        return str(st.secrets.get("DB_URL", "")).split("://", 1)[1].rsplit("@", 1)[0].split(":", 1)[1]
    except Exception:
        return ""


def _stop_with_help(reason: str):
    """Plain-language database error on screen (never shows the password)."""
    st.error("**Database se connect nahi ho pa raha.**\n\n" + reason)
    st.stop()


def _explain(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    hints = []
    if "password authentication failed" in low:
        hints.append("❌ **Password galat hai.** Supabase → Connect → *Reset database password* se naya password "
                     "banao (sirf akshar + number) aur DB_URL mein `postgres.xxxx:` ke baad wahi likho.")
    if "tenant or user not found" in low:
        hints.append("❌ **User ya host galat hai.** User `postgres.<project-code>` hona chahiye (sirf `postgres` nahi) "
                     "aur host bilkul wahi jo Supabase ke *Shared pooler* mein dikhta hai (aws-0-… ya aws-1-…).")
    if "could not translate host name" in low or "name or service not known" in low:
        hints.append("❌ **Host ka naam galat hai** — DB_URL mein `@` ke baad ka hissa Supabase se dobara copy karo. "
                     "Agar password mein `@ # / : ?` hai to bhi ye error aata hai — password badlo.")
    if "network is unreachable" in low or "cannot assign requested address" in low:
        hints.append("❌ **Direct connection wala link laga hai.** Supabase → Connect → *Shared / Transaction pooler* "
                     "wala link lo (`pooler.supabase.com:6543`).")
    if "timeout" in low or "timed out" in low:
        hints.append("⏳ **Database jawab nahi de raha.** Supabase project *Paused* to nahi? Dashboard par "
                     "*Restore project* dabao, 2 minute ruko, phir app *Reboot* karo.")
    pw = _password()
    if pw.strip().lower() in ("[your-password]", "your-password", "apna-db-password", "") or "[" in pw:
        hints.insert(0, "❌ Password ki jagah abhi bhi `[YOUR-PASSWORD]` / `APNA-DB-PASSWORD` ya `[ ]` likha hai.")
    if pw != pw.strip():
        hints.insert(0, "❌ Password ke aage/peeche **space** hai — hata do.")
    if not hints:
        hints.append("Neeche likha error screenshot bhejo.")
    safe = msg.replace(pw, "****") if pw else msg
    return "\n\n".join(hints) + f"\n\n`{safe.strip()[:300]}`"


@st.cache_resource(show_spinner=False)
def _pool():
    try:
        return psycopg2.pool.ThreadedConnectionPool(1, 5, **_db_args())
    except psycopg2.OperationalError as e:
        _stop_with_help(_explain(e))


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
            self.conn = psycopg2.connect(**_db_args())
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


def message_rate_for() -> str:
    """Whose rate a booking message carries when it does not say: TRUCK (default) or PARTY."""
    return (setting("message_rate_for", "TRUCK") or "TRUCK").upper()


def rate_unit() -> str:
    """QUINTAL (default) or TON — how rates are typed and shown."""
    return (setting("rate_unit", "QUINTAL") or "QUINTAL").upper()


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
