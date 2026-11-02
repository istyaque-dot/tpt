"""Party side: hand POD to party (many trips at once) → party shortage / demurrage → receive balance."""

import pandas as pd
import streamlit as st

from core import calc, clock, db, nav, trips, ui

st.markdown("### 🏢 Party: POD & Payment")

MODES = ["By hand", "Courier", "Email", "WhatsApp", "Other"]
SECTIONS = ["🧾 Party settlement", "📤 POD jama karo (bulk)", "⏳ Payment follow-up"]
sel = st.pills("Section", SECTIONS, default=SECTIONS[0], key="psec", label_visibility="collapsed") or SECTIONS[0]

parties = db.accounts("PARTY")
pids = [p["id"] for p in parties]
pn = {p["id"]: p["name"] for p in parties}

# ====================== 1. POD submission (bulk, party-wise) ======================
if sel == SECTIONS[1]:
    party = st.selectbox("Party", pids, format_func=pn.get, index=None, placeholder="Type to search", key="ps_party")
    if party:
        rows = [r for r in trips.load_trips("not t.is_cancelled and t.party_id = %s and t.pod_received", (party,),
                                            "t.loading_date, t.id")
                if not r.get("pod_submitted")]
        if not rows:
            st.success("Is party ki koi POD jama karna baaki nahi. 👍")
        else:
            st.caption(f"{len(rows)} POD received, not yet given to party. Tick the ones you are handing over.")
            n = st.session_state.get("ps_n", 0)
            df = pd.DataFrame([{"id": r["id"], "Give": True, "Truck": r["truck_no"], "Trip": r["trip_no"],
                                "GR": r.get("gr_no") or "", "Loaded": r.get("loading_date"),
                                "Weight": float(r["billing_weight"]), "Balance": float(r["party_balance"])}
                               for r in rows])
            ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"ps_ed_{party}_{n}",
                                disabled=[c for c in df.columns if c != "Give"],
                                column_config={"id": None, "Give": st.column_config.CheckboxColumn("✓"),
                                               "Balance": st.column_config.NumberColumn(format="%.2f")})
            picked = [int(i) for i in ed.loc[ed["Give"], "id"]]
            c1, c2 = st.columns(2)
            sub_date = c1.date_input("Date", value=clock.today(), format="DD/MM/YYYY", key="ps_date")
            mode = c2.selectbox("How", MODES, key="ps_mode")
            ref = st.text_input("Courier docket / person who received", key="ps_ref")
            no_gr = [r["trip_no"] for r in rows if r["id"] in picked and not r.get("gr_no")]
            if no_gr:
                st.warning(f"GR No. missing in: {', '.join(no_gr)}")
            if st.button(f"📤 Mark {len(picked)} POD as given to party", type="primary", use_container_width=True,
                         disabled=not picked):
                for tid_ in picked:
                    trips.update_trip(tid_, {"pod_submitted": True, "pod_submit_date": sub_date,
                                             "pod_submit_mode": mode, "pod_submit_ref": ref.strip() or None})
                st.session_state["ps_n"] = n + 1
                st.session_state["ps_last"] = picked
                ui.flash(f"{len(picked)} POD marked as given to {pn[party]}")
                st.rerun()

        # covering list for the last submission (to print / WhatsApp with the PODs)
        last = st.session_state.get("ps_last")
        if last:
            sub = [trips.get_trip(i) for i in last]
            sub = [s for s in sub if s and s["party_id"] == party]
            if sub:
                with st.expander("📄 Covering list (copy / download)", expanded=True):
                    tot = sum((s["party_balance"] for s in sub), calc.ZERO)
                    lines = [f"POD submission — {pn[party]} — {sub[0]['pod_submit_date']:%d/%m/%Y}", ""]
                    for i, s in enumerate(sub, 1):
                        lines.append(f"{i}. {s['truck_no']} | GR {s.get('gr_no') or '-'} | {calc.route(s)} | "
                                     f"{s['billing_weight']} T | Freight {ui.inr(s['party_freight'])}"
                                     + (f" + Dem {ui.inr(s['party_demurrage'])}" if s["party_demurrage"] else "")
                                     + f" | Bal {ui.inr(s['party_balance'])}")
                    lines += ["", f"Total balance: {ui.inr(tot)}"]
                    st.code("\n".join(lines), language=None)
                    csv = pd.DataFrame([{"Truck": s["truck_no"], "GR No.": s.get("gr_no"), "Trip": s["trip_no"],
                                         "Loaded": s.get("loading_date"), "Route": calc.route(s),
                                         "Weight": float(s["billing_weight"]), "Rate": float(s["party_rate"]),
                                         "Freight": float(s["party_freight"]), "Demurrage": float(s["party_demurrage"]),
                                         "Shortage": float(s["party_shortage"]), "Received": float(s["party_received"]),
                                         "Balance": float(s["party_balance"])} for s in sub])
                    st.download_button("⬇ Download list (Excel/CSV)", csv.to_csv(index=False).encode(),
                                       file_name=f"POD_{pn[party]}_{clock.today()}.csv", mime="text/csv",
                                       use_container_width=True)

# ====================== 2. Party settlement (one trip) ======================
if sel == SECTIONS[0]:
    sid = st.session_state.get("psettle_id")
    t = trips.get_trip(sid) if sid else None
    if not t:
        q = st.text_input("🔎 Truck / GR / Trip / party", key="psq", placeholder="Search trip",
                          label_visibility="collapsed")
        rows = trips.find_trips(q, "Party to receive", 100)
        rows.sort(key=lambda r: (not r.get("pod_submitted"), r.get("loading_date") or clock.today()))
        st.caption(f"{len(rows)} trip(s) with party balance — POD given ones first")
        for r in rows[:40]:
            with st.container(border=True):
                st.markdown(ui.trip_summary_md(r) + ("  \n📤 POD given" if r.get("pod_submitted") else ""))
                if st.button("Settle →", key=f"psgo_{r['id']}", use_container_width=True):
                    st.session_state["psettle_id"] = r["id"]
                    st.rerun()
    else:
        c1, c2 = st.columns([1, 3])
        if c1.button("← Back", use_container_width=True, key="ps_back"):
            st.session_state.pop("psettle_id", None)
            st.rerun()
        c2.markdown(f"**{t['trip_no']} · {t.get('truck_no') or ''}**  \n{t['party_name']}")
        with st.container(border=True):
            st.markdown(ui.trip_summary_md(t))
        locked = t["locks"]["party"]
        if locked:
            st.success("✅ Party side settled. To change, cancel the receipt first.")

        # POD status
        if t.get("pod_submitted"):
            st.success(f"📤 POD given to party on {t['pod_submit_date']:%d/%m/%Y} · {t.get('pod_submit_mode') or ''} "
                       f"{t.get('pod_submit_ref') or ''}")
        elif t["pod_received"]:
            with st.form(f"ps_pod_{t['id']}"):
                st.markdown("**POD not yet given to party**")
                c1, c2 = st.columns(2)
                d_ = c1.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
                m_ = c2.selectbox("How", MODES)
                r_ = st.text_input("Docket / person")
                if st.form_submit_button("📤 Mark POD given", use_container_width=True):
                    trips.update_trip(t["id"], {"pod_submitted": True, "pod_submit_date": d_, "pod_submit_mode": m_,
                                                "pod_submit_ref": r_.strip() or None})
                    ui.flash("POD marked as given")
                    st.rerun()
        else:
            st.warning("POD has not come from the truck yet.")

        # adjustments (live)
        st.markdown("#### Party kat-kaat / Demurrage")

        def num(label, field, step=100.0, help=None):
            v = t.get(field)
            return calc.D(st.number_input(label, min_value=0.0, step=step, key=f"ps_{field}_{t['id']}",
                                          disabled=locked, value=float(v) if v not in (None, 0) else None,
                                          placeholder="0", help=help))

        c1, c2 = st.columns(2)
        with c1:
            p_short = num("Shortage / damage cut by party ₹", "party_shortage_amt")
        with c2:
            p_dem = num("Demurrage charged to party ₹", "party_demurrage_amt",
                        help="Party pays us for truck waiting at their site")
        p_days = st.number_input("Demurrage days (party)", min_value=0, step=1, disabled=locked,
                                 key=f"ps_days_{t['id']}", placeholder="0",
                                 value=int(t["party_demurrage_days"]) if t.get("party_demurrage_days") else None)
        if t["truck_shortage"] or t["truck_demurrage"]:
            st.caption(f"Truck side: shortage cut ₹{ui.inr(t['truck_shortage'])} · demurrage paid "
                       f"₹{ui.inr(t['truck_demurrage'])}")
        changes = {}
        if not locked:
            for f, v in (("party_shortage_amt", p_short), ("party_demurrage_amt", p_dem)):
                if v != calc.D(t.get(f)):
                    changes[f] = v
            if (p_days or None) != t.get("party_demurrage_days"):
                changes["party_demurrage_days"] = p_days or None
        a = calc.trip_amounts(dict(t, **changes))

        st.markdown("#### Final hisaab (party)")
        with st.container(border=True):
            for name, amt, sign in (("Freight", a["party_freight"], "+"), ("Demurrage", a["party_demurrage"], "+"),
                                    ("Received", a["party_received"], "−"),
                                    ("Shortage / damage", a["party_shortage"], "−")):
                if amt or name in ("Freight", "Received"):
                    c1, c2 = st.columns([3, 2])
                    c1.write(name)
                    c2.markdown(f"<div style='text-align:right'>{sign} ₹{ui.inr(amt)}</div>", unsafe_allow_html=True)
            st.divider()
            c1, c2 = st.columns([3, 2])
            c1.markdown("**Balance to receive**")
            c2.markdown(f"<div style='text-align:right;font-size:1.3rem'><b>₹{ui.inr(a['party_balance'])}</b></div>",
                        unsafe_allow_html=True)
            st.caption(f"Trip profit after this: ₹{ui.inr(a['net_profit'])}")
            if changes:
                st.caption("✏️ Changes not saved yet.")
        if changes and st.button("💾 Save party kat-kaat / demurrage", use_container_width=True):
            trips.update_trip(t["id"], changes)
            ui.flash("Saved")
            st.rerun()

        if not locked:
            st.markdown("#### Receive balance")
            accs = sorted(db.money_accounts(), key=lambda x: 0 if x["acc_type"] == "BANK" else 1)
            aids = [x["id"] for x in accs]
            an = {x["id"]: x["name"] for x in accs}
            with st.form(f"ps_rcv_{t['id']}"):
                amount = st.number_input("Amount ₹", min_value=0.0, step=100.0, placeholder="0",
                                         value=float(a["party_balance"]) if a["party_balance"] > 0 else None)
                c1, c2 = st.columns(2)
                acc = c1.selectbox("Into", aids, format_func=an.get, index=ui.remembered("party_bank", aids))
                v_date = c2.date_input("Date", value=clock.today(), format="DD/MM/YYYY")
                ref = st.text_input("UTR / Ref")
                go = st.form_submit_button("💵 Save" + (" changes &" if changes else "") + " receive",
                                           type="primary", use_container_width=True)
            if go:
                amt = calc.r2(calc.D(amount))
                if amt <= 0 or not acc:
                    st.error("Enter amount.")
                else:
                    if changes:
                        trips.update_trip(t["id"], changes)
                    with db.tx() as cur:
                        trips.add_voucher(cur, v_date=v_date, v_type="RECEIPT", purpose=calc.receipt_purpose(
                            dict(t, **a), amt), trip_id=t["id"], amount=amt, dr_account=acc, cr_account=t["party_id"],
                            ref_no=ref, narration=f"{t['party_name']} · {t.get('truck_no') or ''} · {t['trip_no']}")
                    ui.remember("party_bank", acc)
                    ui.flash(f"₹{ui.inr(amt)} received from {t['party_name']}")
                    st.rerun()
            st.caption("Party paid many trucks in one transfer? Use **Party Receipt** (truck-wise split).")
            if st.button("💵 Open Party Receipt", use_container_width=True):
                nav.go("party_receipt")

# ====================== 3. follow-up ======================
if sel == SECTIONS[2]:
    st.caption("POD given to party, payment still pending — oldest first.")
    rows = [r for r in trips.load_trips("not t.is_cancelled and t.pod_submitted", None, "t.pod_submit_date")
            if not calc.party_settled(r, r) and r["party_balance"] > calc.SETTLED_TOLERANCE]
    by_party = {}
    for r in rows:
        by_party.setdefault(r["party_name"], []).append(r)
    if not rows:
        st.success("Koi payment pending nahi. 👍")
    for name, rs in sorted(by_party.items(), key=lambda kv: kv[1][0]["pod_submit_date"]):
        tot = sum((r["party_balance"] for r in rs), calc.ZERO)
        oldest = (clock.today() - rs[0]["pod_submit_date"]).days
        with st.expander(f"{name} · ₹{ui.inr(tot)} · {len(rs)} truck(s) · oldest {oldest} days"):
            df = pd.DataFrame([{"Truck": r["truck_no"], "GR": r.get("gr_no"), "POD given": r["pod_submit_date"],
                                "Days": (clock.today() - r["pod_submit_date"]).days,
                                "Balance": float(r["party_balance"])} for r in rs])
            ui.show_table(df, f"fu_{name[:15]}", money_cols=["Balance"])
