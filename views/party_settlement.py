"""Party side: hand POD to party (many trips at once) → party shortage / demurrage → receive balance."""

import pandas as pd
import streamlit as st

from core import calc, clock, db, nav, trips, ui

st.markdown("### 🏢 Party: POD & Payment")

MODES = ["By hand", "Courier", "Email", "WhatsApp", "Other"]
SECTIONS = ["🧾 Party settlement", "📤 POD jama karo (bulk)", "⏳ Payment follow-up", "📃 Bill banao"]
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
                                    (f"TDS {a['tds_rate']}% (party ne kaata)", a["party_tds"], "−"),
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
    from core import followup

    company = db.setting("company_name", "My Transport")
    today = clock.today()
    sub = st.pills("Follow-up", ["💰 Party se paisa", "📄 Truck se POD"], default="💰 Party se paisa",
                   key="fu_sub", label_visibility="collapsed") or "💰 Party se paisa"
    try:
        last_sent = {(r["kind"], r["ref_id"]): r["at"] for r in db.query(
            "select distinct on (kind, ref_id) kind, ref_id, at from followups order by kind, ref_id, at desc")}
    except Exception:          # followups table not created yet (old schema)
        last_sent = {}

    def sent_label(kind, ref):
        at = last_sent.get((kind, ref))
        if not at:
            return ""
        d = (today - at.astimezone(clock.IST).date()).days if hasattr(at, "astimezone") else 0
        return " · 📨 aaj bheja" if d == 0 else f" · 📨 {d} din pehle bheja"

    def mark_sent(kind, ref, note):
        try:
            db.execute("insert into followups (kind, ref_id, note) values (%s, %s, %s)", (kind, ref, note))
        except Exception as e:
            st.error(f"Note save nahi hua (schema.sql chalao): {e}")

    all_trips = trips.load_trips("not t.is_cancelled", None, "t.id")
    if sub.startswith("💰"):
        dues = followup.party_dues(all_trips, today)
        if not dues:
            st.success("Kisi party ka paisa baaki nahi. 👍")
        else:
            grand = {b[0]: sum((p["buckets"][b[0]] for p in dues), calc.ZERO) for b in followup.BUCKETS}
            ui.metric_grid([(k, ui.inr(v)) for k, v in grand.items()], per_row=4)
            st.caption("Din = POD party ko dene ke din se (POD nahi diya to loading se). Sabse purana upar.")
        mobiles = {p["id"]: p.get("mobile") for p in parties}
        for p in dues:
            head = (f"{'🔴' if p['oldest'] > 30 else '🟠' if p['oldest'] > 15 else '🟢'} {p['party']} · "
                    f"₹{ui.inr(p['total'])} · {len(p['lines'])} truck · {p['oldest']} din"
                    + sent_label("PARTY", p["party_id"]))
            with st.expander(head):
                ui.metric_grid([(k, ui.inr(v)) for k, v in p["buckets"].items() if v], per_row=4)
                df = pd.DataFrame([{"Truck": x["truck_no"], "GR": x["gr_no"], "Trip": x["trip_no"],
                                    "POD diya": "✓" if x["pod_given"] else "—", "Din": x["days"],
                                    "Baaki ₹": float(x["balance"])} for x in p["lines"]])
                ui.show_table(df, f"fu_{p['party_id']}", money_cols=["Baaki ₹"])
                only = st.checkbox("Message mein sirf POD diye hue trucks", value=any(x["pod_given"] for x in p["lines"]),
                                   key=f"fu_only_{p['party_id']}")
                text = followup.party_message(p, company, only_pod_given=only)
                mob = mobiles.get(p["party_id"])
                c1, c2 = st.columns(2)
                c1.link_button("💬 WhatsApp reminder", followup.wa_link(mob, text), use_container_width=True,
                               type="primary")
                if c2.button("✓ Bhej diya", key=f"fu_sent_{p['party_id']}", use_container_width=True):
                    mark_sent("PARTY", p["party_id"], f"₹{p['total']}")
                    st.rerun()
                if not mob:
                    st.caption("Party ka mobile Masters mein daalo to WhatsApp seedha usi chat mein khulega.")
                with st.expander("Message (copy)"):
                    st.code(text, language=None)
    else:
        min_days = st.number_input("Kitne din se purani (unloading / loading se)", min_value=0, value=7, step=1,
                                   key="fu_pod_days")
        pend = followup.pod_pending(all_trips, today, int(min_days))
        tinfo = {r["id"]: r for r in db.query("select t.id, t.driver_mobile, a.mobile owner_mobile from trucks t "
                                                "join accounts a on a.id = t.owner_id")}
        st.caption(f"{len(pend)} trip ki POD abhi truck se nahi aayi.")
        for t in pend[:60]:
            info = tinfo.get(t["truck_id"], {})
            with st.container(border=True):
                st.markdown(f"**{t['truck_no']}** · {t['trip_no']} · {calc.route(t)} · **{t['days']} din**"
                            + (f" · GR {t['gr_no']}" if t.get("gr_no") else "") + sent_label("POD", t["id"]))
                text = followup.pod_message(t, company)
                c1, c2, c3 = st.columns(3)
                c1.link_button("💬 Driver", followup.wa_link(info.get("driver_mobile"), text),
                               use_container_width=True, disabled=not info.get("driver_mobile"))
                c2.link_button("💬 Owner", followup.wa_link(info.get("owner_mobile"), text),
                               use_container_width=True)
                if c3.button("✓ Bheja", key=f"fu_pod_{t['id']}", use_container_width=True):
                    mark_sent("POD", t["id"], "")
                    st.rerun()

# ====================== 4. freight bill ======================
if sel == SECTIONS[3]:
    from core import bills, followup

    party = st.selectbox("Party", pids, format_func=pn.get, index=None, placeholder="Type to search", key="bl_party")
    if not party:
        st.stop()
    co = bills.company()
    if not co["name"] or not co["address"]:
        st.info("Bill par aapka naam, pata, GSTIN, bank — Settings → Bill details mein bhar do.")
    try:
        avail = bills.billable_trips(party)
    except Exception as e:      # bills table / trips.bill_id not created yet
        st.error(f"Pehle Supabase mein latest schema.sql chalao. ({str(e)[:120]})")
        st.stop()

    st.markdown("#### Naya bill")
    if not avail:
        st.caption("Is party ki koi loaded trip bina bill ke nahi bachi.")
    else:
        bn = st.session_state.get("bl_n", 0)
        df = pd.DataFrame([{"Bill": True, "id": t["id"], "Truck": t["truck_no"], "GR": t.get("gr_no") or "",
                            "Date": t.get("loading_date"), "Route": calc.route(t),
                            "Freight ₹": float(t["party_freight"] + t["party_demurrage"]),
                            "POD diya": "✓" if t.get("pod_submitted") else "—"} for t in avail])
        ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"bl_ed_{party}_{bn}",
                            disabled=[c for c in df.columns if c != "Bill"],
                            column_config={"id": None, "Bill": st.column_config.CheckboxColumn("✓"),
                                           "Freight ₹": st.column_config.NumberColumn(format="%.2f"),
                                           "Date": st.column_config.DateColumn(format="DD/MM/YY")})
        chosen = [int(r["id"]) for _, r in ed.iterrows() if r.get("Bill")]
        modes = list(bills.GST_MODES)
        dm = (db.setting("bill_gst_mode", "NONE") or "NONE").upper()
        c1, c2, c3 = st.columns(3)
        mode = c1.selectbox("GST", modes, index=modes.index(dm) if dm in modes else 0, format_func=bills.GST_MODES.get,
                            key="bl_mode")
        rate = c2.number_input("GST %", min_value=0.0, max_value=28.0, step=1.0, key="bl_rate",
                               value=float(db.setting("bill_gst_rate", "5") or 5), disabled=mode == "NONE")
        b_date = c3.date_input("Bill date", value=clock.today(), format="DD/MM/YYYY", key="bl_date")
        lines = [bills.trip_line(t) for t in avail if t["id"] in chosen]
        party_row = next((p for p in parties if p["id"] == party), {})
        tot = bills.totals(lines, mode, rate, bills.same_state(co["gstin"], party_row.get("gstin")))
        ui.metric_grid([("Trips", len(lines)), ("Freight", ui.inr(tot["freight"])),
                        ("GST (bill mein)", ui.inr(tot["gst"])), ("Bill amount", ui.inr(tot["total"]))], per_row=4)
        if mode == "FORWARD":
            st.caption("GST party ke khate mein judega (Party Dr / GST Payable Cr). Trip-wise baaki sirf freight ka rahega.")
        elif mode == "RCM":
            st.caption(f"Bill par note: GST ₹{ui.inr(tot['rcm_gst'])} party khud RCM mein bharegi. Khate mein entry nahi.")
        if st.button(f"💾 Bill banao ({len(lines)} trip)", type="primary", use_container_width=True,
                     disabled=not lines):
            try:
                b = bills.create(party, chosen, b_date, mode, rate)
                st.session_state["bl_n"] = bn + 1
                st.session_state["bl_last"] = b["id"]
                ui.flash(f"Bill {b['bill_no']} ban gaya — ₹{ui.inr(b['total'])}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.markdown("#### Is party ke bill")
    show_rcv = st.checkbox("PDF mein 'Received / Balance' bhi dikhao", value=False, key="bl_show_rcv")
    for b in bills.list_for(party):
        strike = "~~" if b["is_cancelled"] else ""
        with st.expander(f"{strike}{b['bill_no']} · {b['bill_date']:%d/%m/%Y} · ₹{ui.inr(b['total'])} · "
                         f"{len(b['lines'])} trip{strike}" + (" · CANCELLED" if b["is_cancelled"] else ""),
                         expanded=b["id"] == st.session_state.get("bl_last")):
            st.caption(", ".join(f"{x['truck_no']} ({x['trip_no']})" for x in b["lines"]))
            if b["is_cancelled"]:
                st.caption(f"Cancel: {b.get('cancel_reason') or ''}")
                continue
            ch = bills.changed_since_bill(b)
            if ch:
                st.warning(f"Bill ke baad in trips ka freight badla: {', '.join(ch)}. Bill cancel karke naya banao.")
            full = bills.get(b["id"])
            c1, c2 = st.columns(2)
            c1.download_button("⬇ Bill PDF", bills.to_pdf(full, co, show_rcv),
                               file_name=f"Bill_{b['bill_no'].replace('/', '-')}.pdf", mime="application/pdf",
                               use_container_width=True, type="primary", key=f"bl_pdf_{b['id']}")
            c2.link_button("💬 WhatsApp", followup.wa_link(full.get("party_mobile"),
                                                           bills.whatsapp_text(full, co["name"] or "")),
                           use_container_width=True)
            with st.popover("✖ Cancel bill", use_container_width=True):
                why = st.text_input("Kyun?", key=f"bl_why_{b['id']}")
                if st.button("Haan, cancel karo", key=f"bl_cx_{b['id']}", disabled=not why.strip()):
                    bills.cancel(b["id"], why.strip())
                    ui.flash(f"Bill {b['bill_no']} cancel")
                    st.rerun()
