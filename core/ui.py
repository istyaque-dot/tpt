"""Shared UI helpers."""
import hmac
from decimal import Decimal

import pandas as pd
import streamlit as st

from core import calc


def inr(x, signed=False) -> str:
    """Indian number format: 1234567.5 -> '12,34,567.50'."""
    v = calc.D(x)
    neg = v < 0
    v = abs(v).quantize(Decimal("0.01"))
    whole, frac = f"{v:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    s = f"{whole}.{frac}"
    if neg:
        return f"-{s}"
    return f"+{s}" if signed and v > 0 else s


def drcr(x) -> str:
    v = calc.D(x)
    if v == 0:
        return "0.00"
    return f"{inr(abs(v))} {'Dr' if v > 0 else 'Cr'}"


REMEMBER_DAYS = 30


def _login_secret() -> bytes:
    # changing APP_PASSWORD (or LOGIN_SECRET) logs out every remembered phone
    return (str(st.secrets.get("LOGIN_SECRET", "")) + "|" + str(st.secrets.get("APP_PASSWORD", ""))).encode()


def make_login_key(now: float | None = None, days: int = REMEMBER_DAYS) -> str:
    import hashlib
    import time
    exp = int((now or time.time()) + days * 86400)
    sig = hmac.new(_login_secret(), str(exp).encode(), hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{sig}"


def check_login_key(key: str | None, now: float | None = None) -> bool:
    import hashlib
    import time
    try:
        exp_s, sig = (key or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    good = hmac.new(_login_secret(), exp_s.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, good) and exp > (now or time.time())


def _keep_key_in_link():
    """The signed key lives in the app link, so the home-screen icon / bookmark opens without a password."""
    if st.session_state.get("remember"):
        key = st.session_state.get("login_key") or make_login_key()
        st.session_state["login_key"] = key
        if st.query_params.get("k") != key:
            st.query_params["k"] = key


def logout():
    st.session_state.clear()
    st.query_params.clear()


def login_gate() -> bool:
    if st.session_state.get("authed"):
        _keep_key_in_link()
        return True
    if check_login_key(st.query_params.get("k")):
        st.session_state.update(authed=True, remember=True, login_key=st.query_params.get("k"),
                                user=st.secrets.get("APP_USER", "admin"))
        return True

    st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 6, 1])
    with mid:
        st.markdown("## 🚚 Transport Accounts")
        st.caption("Trip · Truck · Party · Cash & Bank")
        with st.form("login"):
            pw = st.text_input("Password", type="password")
            remember = st.checkbox(f"Remember on this phone ({REMEMBER_DAYS} days)", value=True)
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if pw and hmac.compare_digest(pw, str(st.secrets.get("APP_PASSWORD", ""))):
                    st.session_state.update(authed=True, remember=remember,
                                            user=st.secrets.get("APP_USER", "admin"))
                    _keep_key_in_link()
                    st.rerun()
                else:
                    st.error("Wrong password.")
        if st.query_params.get("k"):
            st.caption("Saved login has expired — please log in again.")
    return False


def pick_account(label: str, rows: list[dict], key: str, placeholder="Select...", index=None):
    if not rows:
        st.warning(f"No {label.lower()} found. Add one in Masters first.")
        return None
    ids = [r["id"] for r in rows]
    names = {r["id"]: r["name"] for r in rows}
    return st.selectbox(label, ids, format_func=lambda i: names[i], key=key,
                        index=index, placeholder=placeholder)


def pick_trip(label: str, trips: list[dict], key: str, label_fn):
    if not trips:
        st.info("No matching trips.")
        return None
    by_id = {t["id"]: t for t in trips}
    tid = st.selectbox(label, list(by_id), format_func=lambda i: label_fn(by_id[i]), key=key,
                       index=None, placeholder="Type Trip No., truck no. or GR No. to search")
    return by_id.get(tid)


def money_df(rows: list[dict], cols: dict) -> pd.DataFrame:
    """Build a display DataFrame. cols = {source_key: 'Header'}; Decimal values become float."""
    data = []
    for r in rows:
        data.append({h: (float(r.get(k)) if isinstance(r.get(k), Decimal) else r.get(k))
                     for k, h in cols.items()})
    return pd.DataFrame(data, columns=list(cols.values()))


def show_table(df: pd.DataFrame, key: str, money_cols=(), height=None, download_name=None):
    cfg = {c: st.column_config.NumberColumn(c, format="%.2f") for c in money_cols if c in df.columns}
    kw = {"height": height} if height else {}
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg, key=key, **kw)
    if download_name and not df.empty:
        st.download_button("⬇ Download CSV", df.to_csv(index=False).encode("utf-8"),
                           file_name=f"{download_name}.csv", mime="text/csv", key=f"dl_{key}")


def show_errors(errors):
    for e in errors:
        st.error(e)


# ---------- Mobile helpers ----------

MOBILE_CSS = """
<style>
/* clean, app-like look: no Streamlit footer / menu / deploy badge */
footer, #MainMenu, [data-testid="stStatusWidget"], .stDeployButton, [data-testid="stAppDeployButton"] {
  display: none !important; }
[data-testid="stHeader"] { background: transparent; }
h3 { font-weight: 700 !important; letter-spacing: -0.01em; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px; }
/* Big, easy-to-tap buttons everywhere */
.stButton button, .stFormSubmitButton button, .stDownloadButton button,
[data-testid="stPopover"] > div > button { min-height: 3rem; width: 100%; font-size: 1rem; }
/* 16px inputs stop phones from zooming in while typing */
input, textarea, [data-baseweb="select"] { font-size: 16px !important; }
@media (max-width: 640px) {
  .block-container { padding: 0.8rem 0.6rem 4rem 0.6rem !important; }
  /* keep 2 small fields side by side on a phone instead of stacking everything */
  [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.5rem !important; }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  [data-testid="stHorizontalBlock"] > [data-testid="column"] {
      min-width: 0 !important; width: auto !important; flex: 1 1 0 !important; }
  h1 { font-size: 1.45rem !important; }
  h2, h3 { font-size: 1.15rem !important; }
  [data-testid="stMetricValue"] { font-size: 1.15rem !important; }
}
</style>
"""


def metric_grid(items: list[tuple], per_row: int = 2):
    """[(label, value), ...] shown 2 per row — readable on a phone."""
    for i in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, (label, value) in zip(cols, items[i:i + per_row]):
            col.metric(label, value)


def mobile_css():
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)


def flash(msg: str):
    """Message shown after the next rerun (dialogs close on rerun)."""
    st.session_state["_flash"] = msg


def show_flash():
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.toast(msg, icon="✅")


def amount(label: str, key: str, value=None, step=100.0, **kw):
    """Empty number box (no '0.00' to delete first). Returns Decimal, 0 when blank."""
    v = st.number_input(label, min_value=0.0, value=value, step=step, key=key,
                        placeholder="0", **kw)
    return calc.D(v)


def remembered(key: str, ids: list, default_index=0):
    """Index of the last choice for this key (e.g. last cash/bank used)."""
    last = st.session_state.get(f"_last_{key}")
    if last in ids:
        return ids.index(last)
    return default_index if ids else None


def remember(key: str, value):
    st.session_state[f"_last_{key}"] = value


STATUS_ICON = {"Booked": "📝", "Truck Assigned": "🚚", "Loaded": "📦", "Unloaded": "📥",
               "POD Received": "📄", "Truck Settled": "✔️", "Party Settled": "💵", "Closed": "✅",
               "Cancelled": "❌"}


def trip_summary_md(t: dict) -> str:
    gr = f"GR **{t['gr_no']}**" if t.get("gr_no") else "GR pending"
    truck = f"**{t['truck_no']}**" if t.get("truck_no") else "no truck"
    wt = f" · {t['billing_weight']} T" if t.get("billing_weight") else ""
    lines = [
        f"**{t['trip_no']}** · {truck} · {gr}",
        f"{t.get('party_name', '')} · {calc.route(t)}{wt}",
        f"{STATUS_ICON.get(t['status'], '')} {t['status']}  ·  "
        f"Truck bal ₹{inr(t['truck_balance'])}  ·  Party bal ₹{inr(t['party_balance'])}",
    ]
    if t.get("pod_submitted"):
        lines.append(f"📤 POD given to party {t['pod_submit_date']:%d/%m}" if t.get("pod_submit_date")
                     else "📤 POD given to party")
    if t.get("remarks"):
        lines.append(f"📝 _{t['remarks']}_")
    return "  \n".join(lines)
