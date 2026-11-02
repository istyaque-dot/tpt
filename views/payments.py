"""Cash / Bank entry: every money movement that is not a trip advance/settlement.

Type                      Debit                Credit
Internal transfer         To (cash/bank)       From (cash/bank)
Pump payment              Petrol pump          Cash/Bank
Expense                   Expense head         Cash/Bank
Expense on pump credit    Expense head         Petrol pump      (no money moves now; pump dues go up)
Other payment             Any account          Cash/Bank
Other receipt             Cash/Bank            Any account
Diesel to truck           Truck owner          Petrol pump      (linked to a trip)
"""
from datetime import timedelta

import psycopg2
import streamlit as st

from core import calc, clock, db, forms, nav, trips, ui

st.markdown("### 💰 Cash / Bank Entry")

c1, c2 = st.columns(2)
if c1.button("💸 Truck Advance", use_container_width=True):
    nav.go("truck_advance")
if c2.button("💵 Party Receipt", use_container_width=True):
    nav.go("party_receipt")

KINDS = ["🔁 Internal transfer", "⛽ Pump payment", "🧾 Expense", "⛽ Expense on pump credit",
         "➖ Other payment", "➕ Other receipt", "🛢 Diesel to truck", "💸 Owner: many trips",
         "↔ Adjust advance to trip", "📒 Entries list"]
kind = st.pills("Entry type", KINDS, default=KINDS[0], key="pay_kind") or KINDS[0]

money = db.money_accounts()
mids = [m["id"] for m in money]
mname = {m["id"]: m["name"] for m in money}
pumps = db.accounts("PUMP")
pump_ids = [p["id"] for p in pumps]
pump_name = {p["id"]: p["name"] for p in pumps}


def money_select(label, key, col=st):
    return col.selectbox(label, mids, format_func=mname.get, index=ui.remembered("money", mids), key=key)


def head_select(key, types=("EXPENSE",)):
    """Expense head picker; typing a new name creates the head on save."""
    heads = db.accounts(list(types))
    names = {h["name"]: h["id"] for h in heads}
    return st.selectbox("Expense head", list(names), index=None, accept_new_options=True, key=key,
                        placeholder="e.g. Office rent, Salary, Mobile, Tea — or type new"), names


def head_id(cur, name, names):
    if name in names:
        return names[name]
    cur.execute("insert into accounts (name, acc_type) values (%s, 'EXPENSE') "
                "on conflict (acc_type, name) do update set active = true returning id", (name.strip(),))
    return cur.fetchone()["id"]


def save(msg, money_acc=None):
    if money_acc:
        ui.remember("money", money_acc)
    ui.flash(msg)
    st.rerun()


# ---------- Internal transfer ----------
if kind == KINDS[0]:
    st.caption("Bank → bank, cash → bank (deposit), bank → cash (withdrawal).")
    with st.form("f_contra", clear_on_submit=True):
        amount = ui.amount("Amount ₹", "ct_amt")
        c1, c2 = st.columns(2)
        frm = c1.selectbox("From (money goes out)", mids, format_func=mname.get, index=None, placeholder="From")
        to = c2.selectbox("To (money comes in)", mids, format_func=mname.get, index=None, placeholder="To")
        c1, c2 = st.columns(2)
        v_date = c1.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
        ref = c2.text_input("UTR / Ref")
        nar = st.text_input("Note", placeholder="e.g. Cash deposited / transfer to HDFC")
        if st.form_submit_button("💾 Save transfer", type="primary", use_container_width=True):
            if not frm or not to or frm == to or amount <= 0:
                st.error("Choose two different accounts and an amount.")
            else:
                with db.tx() as cur:
                    trips.add_voucher(cur, v_date=v_date, v_type="CONTRA", purpose="TRANSFER", amount=amount,
                                      dr_account=to, cr_account=frm, ref_no=ref,
                                      narration=nar.strip() or f"Transfer {mname[frm]} → {mname[to]}")
                save(f"₹{ui.inr(amount)} moved {mname[frm]} → {mname[to]}")

# ---------- Pump payment ----------
elif kind == KINDS[1]:
    if not pumps:
        st.warning("Add a petrol pump in Masters.")
    else:
        bal = {r["id"]: -calc.D(r["bal"]) for r in db.query(
            "select a.id, a.opening_balance + coalesce(sum(l.debit - l.credit), 0) bal from accounts a "
            "left join v_ledger l on l.account_id = a.id where a.acc_type = 'PUMP' group by a.id")}
        with st.form("f_pump", clear_on_submit=True):
            pump = st.selectbox("Petrol pump", pump_ids, index=ui.remembered("pump", pump_ids),
                                format_func=lambda i: f"{pump_name[i]} — due ₹{ui.inr(bal.get(i, 0))}")
            amount = ui.amount("Amount ₹", "pp_amt")
            c1, c2 = st.columns(2)
            acc = money_select("Paid from", "pp_acc", c1)
            v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
            ref = st.text_input("UTR / Cheque / Ref")
            if st.form_submit_button("💾 Save pump payment", type="primary", use_container_width=True):
                if amount <= 0 or not acc:
                    st.error("Enter amount.")
                else:
                    with db.tx() as cur:
                        trips.add_voucher(cur, v_date=v_date, v_type="PUMP_PAYMENT", purpose="PUMP", amount=amount,
                                          dr_account=pump, cr_account=acc, ref_no=ref,
                                          narration=f"Payment to {pump_name[pump]}")
                    ui.remember("pump", pump)
                    save(f"₹{ui.inr(amount)} paid to {pump_name[pump]}", acc)

# ---------- Expense (cash/bank) ----------
elif kind == KINDS[2]:
    with st.form("f_exp", clear_on_submit=True):
        head, names = head_select("ex_head")
        amount = ui.amount("Amount ₹", "ex_amt")
        c1, c2 = st.columns(2)
        acc = money_select("Paid from", "ex_acc", c1)
        v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
        nar = st.text_input("Note")
        if st.form_submit_button("💾 Save expense", type="primary", use_container_width=True):
            if not head or amount <= 0 or not acc:
                st.error("Select head and amount.")
            else:
                with db.tx() as cur:
                    hid = head_id(cur, head, names)
                    trips.add_voucher(cur, v_date=v_date, v_type="OTHER", purpose="EXPENSE", amount=amount,
                                      dr_account=hid, cr_account=acc, narration=nar.strip() or head)
                save(f"Expense ₹{ui.inr(amount)} — {head}", acc)

# ---------- Expense on pump credit ----------
elif kind == KINDS[3]:
    st.caption("Diesel/petrol for own vehicle or other expense taken on the pump's credit (not for a hired truck).")
    if not pumps:
        st.warning("Add a petrol pump in Masters.")
    else:
        with st.form("f_pexp", clear_on_submit=True):
            pump = st.selectbox("Petrol pump", pump_ids, format_func=pump_name.get,
                                index=ui.remembered("pump", pump_ids))
            head, names = head_select("pe_head")
            c1, c2 = st.columns(2)
            with c1:
                litres = ui.amount("Litres", "pe_l", step=1.0)
            with c2:
                rate = ui.amount("Rate", "pe_r", step=0.1)
            amount = ui.amount("Amount ₹ (blank = litres × rate)", "pe_amt")
            c1, c2 = st.columns(2)
            v_date = c1.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
            ref = c2.text_input("Slip No.")
            if st.form_submit_button("💾 Save", type="primary", use_container_width=True):
                amt = amount if amount > 0 else calc.r2(litres * rate)
                if not head or amt <= 0:
                    st.error("Select head and amount.")
                else:
                    with db.tx() as cur:
                        hid = head_id(cur, head, names)
                        trips.add_voucher(cur, v_date=v_date, v_type="OTHER", purpose="PUMP_EXPENSE", amount=amt,
                                          dr_account=hid, cr_account=pump, litres=litres or None, rate=rate or None,
                                          ref_no=ref, narration=f"{head} on {pump_name[pump]} credit")
                    ui.remember("pump", pump)
                    save(f"₹{ui.inr(amt)} {head} on {pump_name[pump]} credit")

# ---------- Other payment / receipt ----------
elif kind in (KINDS[4], KINDS[5]):
    out = kind == KINDS[4]
    others = db.accounts(["EXPENSE", "INCOME", "PARTY", "OWNER", "PUMP"])
    labels = {a["id"]: f"{a['name']} ({ {'OWNER': 'Truck owner'}.get(a['acc_type'], a['acc_type'].title()) })"
              for a in others}
    st.caption("Paid to / received from anyone: truck owner (old balance), party (refund), loan, partner, income…"
               if out else "Money in from anyone: party (without trip), commission, loan, partner, other income…")
    with st.form("f_other", clear_on_submit=True):
        acc_other = st.selectbox("Paid to" if out else "Received from", list(labels), format_func=labels.get,
                                 index=None, placeholder="Type to search")
        new_name = st.text_input("…or new account name (created as expense / income head)")
        amount = ui.amount("Amount ₹", "ot_amt")
        c1, c2 = st.columns(2)
        acc = money_select("Cash / Bank", "ot_acc", c1)
        v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
        c1, c2 = st.columns(2)
        ref = c1.text_input("Ref")
        nar = c2.text_input("Note *")
        if st.form_submit_button("💾 Save", type="primary", use_container_width=True):
            if not (acc_other or new_name.strip()) or amount <= 0 or not acc or not nar.strip():
                st.error("Fill account, amount and note.")
            else:
                try:
                    with db.tx() as cur:
                        if not acc_other:
                            cur.execute("insert into accounts (name, acc_type) values (%s, %s) "
                                        "on conflict (acc_type, name) do update set active = true returning id",
                                        (new_name.strip(), "EXPENSE" if out else "INCOME"))
                            acc_other = cur.fetchone()["id"]
                        trips.add_voucher(cur, v_date=v_date, v_type="OTHER", purpose="PAYMENT" if out else "RECEIPT",
                                          amount=amount, dr_account=acc_other if out else acc,
                                          cr_account=acc if out else acc_other, ref_no=ref, narration=nar.strip())
                    save(f"{'Payment' if out else 'Receipt'} ₹{ui.inr(amount)} saved", acc)
                except psycopg2.Error as e:
                    st.error(f"Could not save: {e}")

# ---------- Diesel to truck ----------
elif kind == KINDS[6]:
    q = st.text_input("Truck / Trip / GR", key="ds_q", placeholder="Last digits of truck")
    rows = [r for r in trips.find_trips(q, "All open", 30) if r.get("truck_id")]
    t = ui.pick_trip("Trip", rows, "ds_trip", trips.trip_label)
    if t:
        forms.diesel_single(t, f"ds_form_{t['id']}")

# ---------- Owner: one transfer for many trips ----------
elif kind == KINDS[7]:
    import uuid

    import pandas as pd
    owners = db.accounts("OWNER")
    oids = [o["id"] for o in owners]
    on = {o["id"]: o["name"] for o in owners}
    owner = st.selectbox("Truck owner", oids, format_func=on.get, index=None, placeholder="Type to search")
    if owner:
        rows = [r for r in trips.load_trips("not t.is_cancelled and t.owner_id = %s", (owner,), "t.loading_date, t.id")
                if calc.is_loaded(r) and not calc.truck_settled(r, r) and r["truck_balance"] > calc.SETTLED_TOLERANCE]
        if not rows:
            st.success("Nothing pending for this owner.")
        else:
            total = ui.amount("Total paid ₹", "ob_total")
            c1, c2 = st.columns(2)
            acc = money_select("From", "ob_acc", c1)
            v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY", key="ob_date")
            ref = st.text_input("UTR / Ref", key="ob_ref")
            n = st.session_state.get("ob_n", 0)
            fill = st.session_state.get(f"ob_fill_{owner}", {})
            if st.button("⚡ Auto-fill (POD received first, oldest first)", use_container_width=True,
                         disabled=total <= 0):
                left, fill = total, {}
                for r in sorted(rows, key=lambda r: (not r["pod_received"], r.get("loading_date"))):
                    take = min(r["truck_balance"], left)
                    if take > 0:
                        fill[r["id"]] = float(take)
                        left -= take
                st.session_state[f"ob_fill_{owner}"] = fill
                st.session_state["ob_n"] = n + 1
                st.rerun()
            df = pd.DataFrame([{"id": r["id"], "Amount": fill.get(r["id"], float("nan")), "Truck": r["truck_no"],
                                "Trip": r["trip_no"], "POD": bool(r["pod_received"]),
                                "Balance": float(r["truck_balance"])} for r in rows])
            ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"ob_ed_{owner}_{n}",
                                disabled=[c for c in df.columns if c != "Amount"],
                                column_config={"id": None, "Amount": st.column_config.NumberColumn(min_value=0.0),
                                               "Balance": st.column_config.NumberColumn(format="%.2f")})
            alloc = {int(r["id"]): calc.r2(calc.D(r["Amount"])) for _, r in ed.iterrows()
                     if pd.notna(r["Amount"]) and r["Amount"] > 0}
            sm = calc.split_summary(total, alloc.values())
            ui.metric_grid([("Paid", ui.inr(sm["total"])), ("Trip-wise", ui.inr(sm["allocated"])),
                            ("Left", ui.inr(sm["on_account"]))], per_row=3)
            if sm["on_account"] != 0:
                st.caption("Trip-wise total must equal the amount paid.")
            if st.button("💾 Save payment", type="primary", use_container_width=True,
                         disabled=sm["total"] <= 0 or sm["on_account"] != 0 or not acc):
                by_id = {r["id"]: r for r in rows}
                req_gr = db.setting_bool("require_gr_for_truck_balance")
                errs = []
                for tid_, amt in alloc.items():
                    t = by_id[tid_]
                    purpose = "BALANCE" if t["pod_received"] else "ADVANCE"
                    errs += [f"{t['trip_no']}: {e}" for e in calc.check_truck_payment(t, t, purpose, amt, req_gr, False)]
                if errs:
                    ui.show_errors(errs)
                else:
                    batch = "P" + uuid.uuid4().hex[:10].upper()
                    with db.tx() as cur:
                        for tid_, amt in alloc.items():
                            t = by_id[tid_]
                            purpose = "BALANCE" if t["pod_received"] else "ADVANCE"
                            trips.add_voucher(cur, v_date=v_date, v_type="PAYMENT", purpose=purpose, trip_id=tid_,
                                              amount=amt, dr_account=owner, cr_account=acc, ref_no=ref, batch_no=batch,
                                              narration=f"{on[owner]} · {t['truck_no']} · {t['trip_no']}")
                    st.session_state.pop(f"ob_fill_{owner}", None)
                    st.session_state["ob_n"] = n + 1
                    save(f"₹{ui.inr(sm['total'])} paid to {on[owner]} for {len(alloc)} trip(s)", acc)

# ---------- Adjust on-account advance to a trip ----------
elif kind == KINDS[8]:
    st.caption("Party ne pehle 'on account' advance diya tha, ya truck owner ko bina trip advance diya tha — "
               "use ab kisi trip mein jodo. Paisa dobara nahi hilta; sirf trip-wise hisaab sahi hota hai.")
    adj = db.system_accounts().get("ADV_ADJ")
    if not adj:
        st.warning("Run the latest schema.sql once (adds the 'Advance Adjustment' account).")
    else:
        side = st.radio("Whose advance?", ["Party", "Truck owner"], horizontal=True)
        acc_type = "PARTY" if side == "Party" else "OWNER"
        accs = db.accounts(acc_type)
        free = {r["id"]: calc.D(r["free"]) for r in db.query(
            "select a.id, a.opening_balance + coalesce(sum(l.debit - l.credit) filter (where l.trip_id is null), 0) free "
            "from accounts a left join v_ledger l on l.account_id = a.id where a.acc_type = %s group by a.id",
            (acc_type,))}
        sign = -1 if acc_type == "PARTY" else 1        # party advance = credit, owner advance = debit
        avail = {i: v * sign for i, v in free.items() if v * sign > calc.SETTLED_TOLERANCE}
        if not avail:
            st.info("No unadjusted advance found.")
        else:
            names = {a["id"]: a["name"] for a in accs if a["id"] in avail}
            who = st.selectbox(side, list(names), format_func=lambda i: f"{names[i]} — advance ₹{ui.inr(avail[i])}",
                               index=None, placeholder="Select")
            if who:
                key_ = "party_id" if acc_type == "PARTY" else "owner_id"
                rows = [r for r in trips.load_trips(f"not t.is_cancelled and t.{key_} = %s", (who,), "t.id")
                        if (r["party_balance"] if acc_type == "PARTY" else r["truck_balance"]) > calc.SETTLED_TOLERANCE]
                t = ui.pick_trip("Trip", rows, "adj_trip", trips.trip_label)
                if t:
                    due = t["party_balance"] if acc_type == "PARTY" else t["truck_balance"]
                    with st.form("f_adj", clear_on_submit=True):
                        amount = st.number_input("Amount to adjust ₹", min_value=0.0, step=100.0,
                                                 value=float(min(due, avail[who])))
                        v_date = st.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
                        if st.form_submit_button("↔ Adjust", type="primary", use_container_width=True):
                            amt = calc.r2(calc.D(amount))
                            if amt <= 0 or amt > avail[who] + calc.SETTLED_TOLERANCE:
                                st.error(f"Amount must be between 0 and the advance ₹{ui.inr(avail[who])}.")
                            else:
                                batch = "A" + __import__("uuid").uuid4().hex[:10].upper()   # cancel together
                                with db.tx() as cur:
                                    if acc_type == "PARTY":
                                        # take it off 'on account' … and put it on the trip as a receipt
                                        trips.add_voucher(cur, v_date=v_date, v_type="OTHER", purpose="ADJUST",
                                                          amount=amt, dr_account=who, cr_account=adj,
                                                          narration=f"Advance moved to {t['trip_no']}", batch_no=batch)
                                        trips.add_voucher(cur, v_date=v_date, v_type="RECEIPT", purpose="ADJUST",
                                                          trip_id=t["id"], amount=amt, dr_account=adj, cr_account=who,
                                                          narration=f"Old advance adjusted · {t['trip_no']}", batch_no=batch)
                                    else:
                                        trips.add_voucher(cur, v_date=v_date, v_type="OTHER", purpose="ADJUST",
                                                          amount=amt, dr_account=adj, cr_account=who,
                                                          narration=f"Advance moved to {t['trip_no']}", batch_no=batch)
                                        trips.add_voucher(cur, v_date=v_date, v_type="PAYMENT", purpose="ADJUST",
                                                          trip_id=t["id"], amount=amt, dr_account=who, cr_account=adj,
                                                          narration=f"Old advance adjusted · {t['trip_no']}", batch_no=batch)
                                save(f"₹{ui.inr(amt)} advance adjusted to {t['trip_no']}")

# ---------- Entries list + cancel ----------
else:
    c1, c2 = st.columns(2)
    d_from = c1.date_input("From", value=clock.today() - timedelta(days=30), format="DD/MM/YYYY", key="el_from")
    d_to = c2.date_input("To", value=clock.today(), format="DD/MM/YYYY", key="el_to")
    types = st.multiselect("Type", ["RECEIPT", "PAYMENT", "DIESEL", "PUMP_PAYMENT", "CONTRA", "OTHER", "TRIP"],
                           default=["RECEIPT", "PAYMENT", "DIESEL", "PUMP_PAYMENT", "CONTRA", "OTHER"])
    vrows = db.query(trips.VOUCHER_LIST_SQL + " where v.v_date between %s and %s and v.v_type = any(%s) "
                     "order by v.v_date desc, v.id desc", (d_from, d_to, types or ["NONE"]))
    vdf = ui.money_df(vrows, {"id": "No.", "v_date": "Date", "v_type": "Type", "purpose": "For", "trip_no": "Trip",
                              "amount": "Amount", "debit_account": "Debit", "credit_account": "Credit",
                              "ref_no": "Ref", "narration": "Note", "is_cancelled": "Cancelled",
                              "cancel_reason": "Cancel reason"})
    ui.show_table(vdf, "entries", money_cols=["Amount"], download_name="entries")

    st.markdown("**Cancel a wrong entry** (never deleted; cancelled ones stay visible)")
    st.caption("A party bank receipt split over many trucks is cancelled together (whole bank entry).")
    cancellable = [v for v in vrows if not v["is_cancelled"] and v["v_type"] != "TRIP"]
    with st.form("cancel_v"):
        vid = st.selectbox("Entry", [v["id"] for v in cancellable], index=None,
                           format_func=lambda i: next(f"#{v['id']} · {v['v_date']:%d/%m} · {v['v_type']} · "
                                                      f"₹{ui.inr(v['amount'])} · {v['trip_no'] or ''} {v['narration'] or ''}"
                                                      for v in cancellable if v["id"] == i))
        reason = st.text_input("Reason *")
        if st.form_submit_button("Cancel entry"):
            if not vid or not reason.strip():
                st.error("Select the entry and give a reason.")
            else:
                try:
                    trips.cancel_voucher(vid, reason.strip())
                    save("Entry cancelled")
                except ValueError as e:
                    st.error(str(e))
