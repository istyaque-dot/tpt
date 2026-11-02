"""Statements: Party · Petrol Pump · Truck Owner · Trip — on screen, PDF, WhatsApp, CSV."""
from datetime import timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

from core import calc, clock, db, statements, trips, ui

st.markdown("### 📑 Statements")

KINDS = ["🏢 Party", "⛽ Petrol Pump", "🚚 Truck Owner", "🧾 Trip"]
kind = st.pills("Statement", KINDS, default=KINDS[0], key="stm_kind", label_visibility="collapsed") or KINDS[0]


def show(s: dict, phone: str | None, file_stub: str):
    """Statement on screen + PDF / WhatsApp / CSV."""
    with st.container(border=True):
        st.markdown(f"**{s['title']} — {s['name']}**" + (f"  \n{s['period']}" if s.get("period") else ""))
        if s.get("info"):
            st.markdown("  \n".join(f"**{k}:** {v}" for k, v in s["info"]))
        ui.metric_grid([(k, ui.inr(v)) for k, v in s["summary"]])

    company = db.setting("company_name", "My Transport")
    c1, c2 = st.columns(2)
    c1.download_button("⬇ PDF", statements.to_pdf(s, company), file_name=f"{file_stub}.pdf",
                       mime="application/pdf", use_container_width=True, type="primary")
    c2.download_button("⬇ Excel (CSV)", pd.DataFrame(statements.to_rows(s)).to_csv(index=False).encode(),
                       file_name=f"{file_stub}.csv", mime="text/csv", use_container_width=True)
    text = statements.to_text(s)
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    wa = f"https://wa.me/91{digits}?text=" if len(digits) == 10 else "https://wa.me/?text="
    if len(text) < 3500:
        st.link_button("💬 Send on WhatsApp", wa + quote(text), use_container_width=True)
    else:
        st.caption("Statement is long for WhatsApp text — send the PDF instead.")
    with st.expander("WhatsApp text (copy)"):
        st.code(text, language=None)

    for t in s["tables"]:
        if not t["rows"]:
            continue
        st.markdown(f"**{t['heading']}**")
        body = t["rows"] + ([t["total"]] if t.get("total") else [])
        df = pd.DataFrame([[statements._fmt(v, i in t["money"]) for i, v in enumerate(r)] for r in body],
                          columns=t["columns"])
        st.dataframe(df, hide_index=True, use_container_width=True)
    if s.get("note"):
        st.caption(s["note"])


def period(key: str):
    today = clock.today()
    c1, c2 = st.columns(2)
    d_from = c1.date_input("From", value=today.replace(day=1) if today.day > 1 else today - timedelta(days=30),
                           format="DD/MM/YYYY", key=f"{key}_f")
    d_to = c2.date_input("To", value=today, format="DD/MM/YYYY", key=f"{key}_t")
    return d_from, d_to


def account_pick(acc_type: str, label: str, key: str):
    accs = db.accounts(acc_type, active_only=False)
    ids = [a["id"] for a in accs]
    names = {a["id"]: a["name"] for a in accs}
    pre = st.session_state.get(f"{key}_pre")
    return st.selectbox(label, ids, format_func=names.get, key=key, placeholder="Type to search",
                        index=ids.index(pre) if pre in ids else None), {a["id"]: a for a in accs}


if kind == KINDS[0]:
    pid, accs = account_pick("PARTY", "Party", "stm_party")
    d_from, d_to = period("stm_p")
    if pid:
        s = statements.account_statement(pid, d_from, d_to, "PARTY")
        show(s, accs[pid].get("mobile"), f"Party_{accs[pid]['name']}_{d_from}_{d_to}")

elif kind == KINDS[1]:
    pid, accs = account_pick("PUMP", "Petrol pump", "stm_pump")
    d_from, d_to = period("stm_pp")
    if pid:
        s = statements.account_statement(pid, d_from, d_to, "PUMP")
        show(s, accs[pid].get("mobile"), f"Pump_{accs[pid]['name']}_{d_from}_{d_to}")

elif kind == KINDS[2]:
    oid, accs = account_pick("OWNER", "Truck owner", "stm_owner")
    d_from, d_to = period("stm_o")
    if oid:
        s = statements.account_statement(oid, d_from, d_to, "OWNER")
        show(s, accs[oid].get("mobile"), f"Owner_{accs[oid]['name']}_{d_from}_{d_to}")

else:
    pre = st.session_state.get("stm_trip_id")
    t = trips.get_trip(pre) if pre else None
    q = st.text_input("Truck / GR / Trip No.", key="stm_tq", placeholder="Last digits of truck, GR or Trip No.")
    if q.strip():
        found = trips.find_trips(q, "All", 15)
        pick = ui.pick_trip("Trip", found, "stm_trip_pick", lambda x: f"{trips.trip_label(x)} · {x['status']}")
        t = pick or t
    if t:
        st.session_state["stm_trip_id"] = t["id"]
        s = statements.trip_statement(t["id"])
        owner_mobile = None
        if t.get("owner_id"):
            owner_mobile = (db.one("select mobile from accounts where id=%s", (t["owner_id"],)) or {}).get("mobile")
        show(s, owner_mobile, f"Trip_{t['trip_no']}_{t.get('truck_no') or ''}")
        if calc.is_loaded(t):
            st.caption("WhatsApp button opens chat with the truck owner (if mobile saved in Masters).")
