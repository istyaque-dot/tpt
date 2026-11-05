"""One message, many trucks: check all rows in one table and save every trip in one go."""
import pandas as pd
import psycopg2
import streamlit as st

from core import calc, clock, db, smart, trips, ui


def render(rows: list[dict], trucks_: list[dict], parties: list[dict], n: int):
    SS = st.session_state
    RU = db.rate_unit()
    lab = calc.rate_label(RU)
    pids = [p["id"] for p in parties]
    pnames = {p["id"]: p["name"] for p in parties}

    st.success(f"🚚 Message mein **{len(rows)} trucks** mile — table check karo, phir ek saath Save.")
    for r in rows:
        for note in r.get("notes", []):
            if note.startswith("⚠️"):
                st.warning(note)

    # ---- details common to all trucks ----
    first = rows[0] if rows else {}
    history = db.query("select party_id, to_place, from_place, material, party_rate, truck_rate, commission_value, "
                       "owner_id, booking_date, tds_rate from trips where not is_cancelled order by id desc limit 500")
    kp, kf, kc, kt = f"mt_party_{n}", f"mt_freight_{n}", f"mt_comm_{n}", f"mt_tds_{n}"
    if kp not in SS:
        guess = first.get("party_id") or smart.suggest(history, first.get("to_place", "")).get("party_id", (None,))[0]
        SS[kp] = guess if guess in pids else None
    if kc not in SS:
        c = smart.suggest(history, "").get("commission")
        SS[kc] = float(c[0]) if c else None
    if kt not in SS:
        SS[kt] = float(db.setting("default_tds_rate", "1") or 0)
    party_id = st.selectbox("Freight paid by (company) — sab trucks ke liye *", pids, format_func=pnames.get,
                            key=kp, index=None, placeholder="Type to search")
    c1, c2 = st.columns(2)
    with c1:
        common_freight = ui.amount(f"Freight {lab} (sab ke liye)", kf, step=1.0,
                                   help="Kisi truck ka alag ho to table mein us row mein likho")
        sug = smart.suggest(history, first.get("to_place", ""), party_id)
        if "party_rate" in sug and not SS.get(kf):
            v = float(calc.rate_show(sug["party_rate"][0], RU))
            st.button(f"↩ Freight pichhli baar ₹{v:g}", key=f"mt_last_{n}", on_click=SS.__setitem__, args=(kf, v))
    with c2:
        comm = ui.amount("Commission ₹ (har truck)", kc, step=50.0)
    c1, c2 = st.columns(2)
    tds_rate = calc.D(c1.number_input("Party TDS %", min_value=0.0, max_value=10.0, step=0.5, key=kt))
    trip_date = c2.date_input("Trip date", value=clock.today(), format="DD/MM/YYYY", key=f"mt_date_{n}")

    # ---- one row per truck ----
    def show_rate(v):
        return float(calc.rate_show(v, RU)) if v else None

    df = pd.DataFrame([{
        "Save": True, "Truck": r.get("truck_no") or "", "From": r.get("from_place") or "", "To": r.get("to_place") or "",
        "Weight T": float(r["weight"]) if r.get("weight") else None,
        f"Truck {lab}": show_rate(r.get("truck_rate")), f"Freight {lab}": show_rate(r.get("party_rate")),
        "GR": r.get("gr_no") or "",
        "Comment": " · ".join(x for x in (f"{r['points']} point" if r.get("points") else "",
                                          f"Adv {r['advance']}" if r.get("advance") else "",
                                          f"Driver {r['mobile']}" if r.get("mobile") else "") if x),
    } for r in rows])
    st.caption(f"Freight {lab} khaali = upar wala 'sab ke liye' freight. Weight khaali = abhi load nahi hua.")
    ed = st.data_editor(df, hide_index=True, use_container_width=True, num_rows="dynamic", key=f"mt_ed_{n}",
                        column_config={"Save": st.column_config.CheckboxColumn("✓", default=True),
                                       "Weight T": st.column_config.NumberColumn(min_value=0.0, format="%.3f"),
                                       f"Truck {lab}": st.column_config.NumberColumn(min_value=0.0),
                                       f"Freight {lab}": st.column_config.NumberColumn(min_value=0.0)})

    # ---- totals ----
    tot_hire = tot_fr = calc.ZERO
    for _, r in ed.iterrows():
        if r.get("Save") and pd.notna(r.get("Weight T")):
            w = calc.D(r["Weight T"])
            tr = calc.rate_store(r[f"Truck {lab}"] or 0, RU) if pd.notna(r[f"Truck {lab}"]) else calc.ZERO
            fr_shown = r[f"Freight {lab}"] if pd.notna(r[f"Freight {lab}"]) and r[f"Freight {lab}"] else common_freight
            tot_hire += w * tr
            tot_fr += w * calc.rate_store(fr_shown, RU)
    if tot_hire or tot_fr:
        ui.metric_grid([("Kul truck hire", ui.inr(tot_hire)), ("Kul freight", ui.inr(tot_fr)),
                        ("Profit (commission ke saath)", ui.inr(tot_fr - tot_hire + comm * int(ed["Save"].sum())))],
                       per_row=3)

    c1, c2 = st.columns(2)
    if c2.button("✖ Cancel", use_container_width=True, key=f"mt_cancel_{n}"):
        SS.pop("nt_multi", None)
        SS["nt_n"] = n + 1
        st.rerun()
    if not c1.button(f"💾 {int(ed['Save'].sum())} trips Save karo", type="primary", use_container_width=True,
                     key=f"mt_save_{n}"):
        return

    errs, todo = [], []
    if not party_id:
        errs.append("Company (party) chuno.")
    for i, r in ed.iterrows():
        if not r.get("Save"):
            continue
        label = f"Row {i + 1} ({r['Truck'] or '?'})"
        hit = trips.find_truck(r["Truck"] or "", trucks_)
        new_no = None
        if not hit:
            if trips.looks_like_truck_no(r["Truck"] or ""):
                new_no = calc.normalize_truck_no(r["Truck"])
            else:
                errs.append(f"{label}: truck no. sahi likho.")
                continue
        if not str(r["To"] or "").strip():
            errs.append(f"{label}: destination likho.")
        tr = calc.rate_store(r[f"Truck {lab}"], RU) if pd.notna(r[f"Truck {lab}"]) else calc.ZERO
        fr_shown = r[f"Freight {lab}"] if pd.notna(r[f"Freight {lab}"]) and r[f"Freight {lab}"] else common_freight
        fr = calc.rate_store(fr_shown, RU)
        if tr <= 0:
            errs.append(f"{label}: truck rate likho.")
        if fr <= 0:
            errs.append(f"{label}: freight likho (row mein ya upar 'sab ke liye').")
        w = calc.D(r["Weight T"]) if pd.notna(r["Weight T"]) else calc.ZERO
        todo.append((label, hit["id"] if hit else None, new_no, r, tr, fr, w))
    if errs:
        ui.show_errors(errs)
        return
    saved, failed = [], []
    for label, truck_id, new_no, r, tr, fr, w in todo:
        to = str(r["To"]).strip()
        try:
            tid = trips.create_trip(dict(
                booking_date=trip_date, party_id=party_id, from_place=str(r["From"] or "").strip() or None,
                to_place=to.title() if to.islower() else to, party_rate=fr, truck_id=truck_id, truck_rate=tr,
                loaded_weight=w if w > 0 else None, loading_date=trip_date if w > 0 else None,
                gr_no=str(r["GR"] or ""), gr_date=trip_date if str(r["GR"] or "").strip() else None,
                freight_basis=db.setting("freight_basis", "LOADED"), commission_type="FIXED",
                commission_value=comm, tds_rate=tds_rate, remarks=str(r["Comment"] or "").strip() or None),
                new_truck_no=new_no)
            saved.append(trips.get_trip(tid)["trip_no"])
        except psycopg2.errors.UniqueViolation:
            failed.append(f"{label}: GR No. {r['GR']} pehle se kisi trip mein hai — ye trip save nahi hui.")
        except Exception as e:  # keep going; report at the end
            failed.append(f"{label}: {e}")
    for f in failed:
        st.error(f)
    if saved:
        SS.pop("nt_multi", None)
        SS["nt_n"] = n + 1
        ui.flash(f"{len(saved)} trips saved: {', '.join(saved)}" + (f" · {len(failed)} nahi hui" if failed else ""))
        if not failed:
            st.rerun()
