import psycopg2
import streamlit as st

from core import calc, db, ui

st.markdown("### 📇 Masters")

KINDS = {
    "Parties": ("PARTY", ["mobile", "address", "gstin"], "Receivable (party owes us)"),
    "Truck Owners": ("OWNER", ["mobile", "pan", "bank_details"], "Payable (we owe owner)"),
    "Petrol Pumps": ("PUMP", ["location", "mobile"], "Payable (we owe pump)"),
    "Bank Accounts": ("BANK", ["account_no"], "Balance in bank"),
    "Income / Expense Heads": ("EXPENSE", [], "Opening"),
}
LABELS = {"mobile": "Mobile", "address": "Address", "gstin": "GSTIN", "pan": "PAN",
          "bank_details": "Bank details (A/c, IFSC)", "location": "Location", "account_no": "A/c No."}
# which sign the "natural" opening balance has: +1 = Debit, -1 = Credit
NATURAL_SIGN = {"PARTY": 1, "OWNER": -1, "PUMP": -1, "BANK": 1, "EXPENSE": 1, "INCOME": -1, "CASH": 1}


def account_form(acc_type: str, fields: list[str], open_label: str, existing: dict | None, key: str):
    with st.form(key, clear_on_submit=existing is None):
        name = st.text_input("Name *", value=(existing or {}).get("name", ""))
        vals = {}
        cols = st.columns(2)
        for i, f in enumerate(fields):
            vals[f] = cols[i % 2].text_input(LABELS[f], value=(existing or {}).get(f) or "")
        if acc_type == "EXPENSE":
            head_type = st.radio("Head type", ["EXPENSE", "INCOME"], horizontal=True,
                                 index=0 if (existing or {}).get("acc_type", "EXPENSE") == "EXPENSE" else 1)
        else:
            head_type = acc_type
        sign = NATURAL_SIGN[head_type]
        ob = calc.D((existing or {}).get("opening_balance"))
        c1, c2 = st.columns(2)
        ob_amt = c1.number_input(f"Opening balance — {open_label}", min_value=0.0, step=100.0,
                                 value=float(abs(ob)))
        reverse = c2.checkbox("Opposite side (advance / extra paid)",
                              value=bool(ob) and (ob > 0) != (sign > 0),
                              help="Tick if the opening balance is on the other side, e.g. a party paid advance.")
        active = st.checkbox("Active", value=(existing or {}).get("active", True))
        if st.form_submit_button("Save", type="primary"):
            if not name.strip():
                st.error("Name is required.")
                return
            opening = calc.D(ob_amt) * sign * (-1 if reverse else 1)
            data = {"name": name.strip(), "acc_type": head_type, "opening_balance": opening,
                    "active": active, **{f: (vals[f].strip() or None) for f in fields}}
            try:
                if existing:
                    sets = ", ".join(f"{k}=%s" for k in data)
                    db.execute(f"update accounts set {sets} where id=%s", list(data.values()) + [existing["id"]])
                else:
                    cols_ = ", ".join(data)
                    db.execute(f"insert into accounts ({cols_}) values ({', '.join(['%s'] * len(data))})",
                               list(data.values()))
                st.success("Saved.")
                st.rerun()
            except psycopg2.errors.UniqueViolation:
                st.error("This name already exists.")


tabs = st.tabs(list(KINDS) + ["Trucks", "Places & Materials", "Cash"])

for tab, (title, (acc_type, fields, open_label)) in zip(tabs, KINDS.items()):
    with tab:
        types = ["EXPENSE", "INCOME"] if acc_type == "EXPENSE" else [acc_type]
        rows = [r for r in db.accounts(types, active_only=False) if not r["system_code"]]
        mode = st.radio("Action", ["Add new", "Edit existing"], horizontal=True, key=f"mode_{acc_type}")
        if mode == "Add new":
            account_form(acc_type, fields, open_label, None, f"add_{acc_type}")
        else:
            sel = ui.pick_account(title, rows, f"edit_sel_{acc_type}")
            if sel:
                account_form(acc_type, fields, open_label, next(r for r in rows if r["id"] == sel),
                             f"edit_{acc_type}_{sel}")
        st.divider()
        df = ui.money_df(rows, {"name": "Name", "acc_type": "Type",
                                **{f: LABELS[f] for f in fields},
                                "opening_balance": "Opening (+Dr / -Cr)", "active": "Active"})
        ui.show_table(df, f"list_{acc_type}", money_cols=["Opening (+Dr / -Cr)"])

# ---------- Trucks ----------
with tabs[len(KINDS)]:
    owners = db.accounts("OWNER")
    trucks = db.query("select t.*, a.name owner_name from trucks t join accounts a on a.id=t.owner_id "
                      "order by t.truck_no")
    mode = st.radio("Action", ["Add new", "Edit existing"], horizontal=True, key="mode_truck")
    existing = None
    if mode == "Edit existing" and trucks:
        tid = st.selectbox("Truck", [t["id"] for t in trucks], index=None,
                           format_func=lambda i: next(t["truck_no"] for t in trucks if t["id"] == i))
        existing = next((t for t in trucks if t["id"] == tid), None)
    if mode == "Add new" or existing:
        with st.form(f"truck_form_{(existing or {}).get('id', 'new')}", clear_on_submit=existing is None):
            truck_no = st.text_input("Truck No. *", value=(existing or {}).get("truck_no", ""))
            owner_ids = [o["id"] for o in owners]
            owner = st.selectbox("Owner *", owner_ids, format_func=lambda i: next(o["name"] for o in owners if o["id"] == i),
                                 index=owner_ids.index(existing["owner_id"]) if existing and existing["owner_id"] in owner_ids else None)
            c1, c2 = st.columns(2)
            dname = c1.text_input("Driver name", value=(existing or {}).get("driver_name") or "")
            dmob = c2.text_input("Driver mobile", value=(existing or {}).get("driver_mobile") or "")
            active = st.checkbox("Active", value=(existing or {}).get("active", True))
            st.caption("Owner not in list? Add in the 'Truck Owners' tab first.")
            if st.form_submit_button("Save", type="primary"):
                tn = calc.normalize_truck_no(truck_no)
                if not tn or not owner:
                    st.error("Truck No. and Owner are required.")
                else:
                    try:
                        if existing:
                            db.execute("update trucks set truck_no=%s, owner_id=%s, driver_name=%s, driver_mobile=%s, "
                                       "active=%s where id=%s", (tn, owner, dname or None, dmob or None, active, existing["id"]))
                            st.info("Changing the owner affects only new trips. Old trips keep their owner.")
                        else:
                            db.execute("insert into trucks (truck_no, owner_id, driver_name, driver_mobile, active) "
                                       "values (%s,%s,%s,%s,%s)", (tn, owner, dname or None, dmob or None, active))
                        st.success(f"Saved {tn}.")
                        st.rerun()
                    except psycopg2.errors.UniqueViolation:
                        st.error("This truck number already exists.")
    st.divider()
    ui.show_table(ui.money_df(trucks, {"truck_no": "Truck No.", "owner_name": "Owner", "driver_name": "Driver",
                                       "driver_mobile": "Driver mobile", "active": "Active"}), "trucks_list")

# ---------- Places / materials ----------
with tabs[len(KINDS) + 1]:
    st.caption("These lists fill automatically from trips. You can also add here.")
    c1, c2 = st.columns(2)
    for col, kind, label in ((c1, "PLACE", "Place"), (c2, "MATERIAL", "Material")):
        with col:
            with st.form(f"lk_{kind}", clear_on_submit=True):
                v = st.text_input(f"New {label.lower()}")
                if st.form_submit_button(f"Add {label}") and v.strip():
                    db.execute("insert into lookups(kind,name) values (%s,%s) on conflict do nothing", (kind, v.strip()))
                    st.rerun()
            st.write(", ".join(db.lookups(kind)) or "—")

# ---------- Cash ----------
with tabs[len(KINDS) + 2]:
    cash = db.one("select * from accounts where system_code='CASH'")
    with st.form("cash_ob"):
        v = st.number_input("Opening cash in hand", value=float(cash["opening_balance"]), step=100.0)
        if st.form_submit_button("Save", type="primary"):
            db.execute("update accounts set opening_balance=%s where id=%s", (v, cash["id"]))
            st.success("Saved.")
