
import streamlit as st

from core import clock, db, drive, trips, ui

st.markdown("### 📄 GR / POD Documents")

SECTIONS = ["🧾 Fill GR No.", "🤖 Scanned POD (AI kaatega)", "⬆ Bulk upload (GR-wise files)", "📋 Missing documents"]
sel = st.pills("Section", SECTIONS, default=SECTIONS[0], key="dsec", label_visibility="collapsed") or SECTIONS[0]

if sel == SECTIONS[0]:
    st.caption("All trips waiting for GR No. Type the GR No. in the row and press Save — many at once.")
    q = st.text_input("Search truck / party", key="grf_q", placeholder="Truck last digits or party")
    pend = trips.find_trips(q, "GR pending", 500)
    pend = [r for r in pend if r.get("truck_id")]
    if not pend:
        st.success("No GR pending. 👍")
    else:
        import pandas as pd
        df = pd.DataFrame([{"id": r["id"], "GR No.": "", "Truck": r["truck_no"], "Trip": r["trip_no"],
                            "Date": r.get("loading_date") or r["booking_date"], "Party": r["party_name"],
                            "To": r["to_place"]} for r in pend])
        n = st.session_state.get("grf_n", 0)
        ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"grf_ed_{n}",
                            disabled=[c for c in df.columns if c != "GR No."],
                            column_config={"id": None, "GR No.": st.column_config.TextColumn(required=False)})
        filled = ed[ed["GR No."].fillna("").str.strip() != ""]
        if st.button(f"💾 Save {len(filled)} GR No.", type="primary", use_container_width=True,
                     disabled=filled.empty):
            import psycopg2
            ok, errs = 0, []
            for _, r in filled.iterrows():
                try:
                    trips.update_trip(int(r["id"]), {"gr_no": r["GR No."], "gr_date": clock.today()})
                    ok += 1
                except psycopg2.errors.UniqueViolation:
                    errs.append(f"{r['Trip']} ({r['Truck']}): GR {r['GR No.']} is already used in another trip.")
            for e in errs:
                st.error(e)
            if ok:
                st.session_state["grf_n"] = n + 1
                ui.flash(f"{ok} GR No. saved")
                if not errs:
                    st.rerun()

if sel == SECTIONS[1]:
    from core import ai
    st.markdown("Saare POD ek saath scan karke **ek PDF** daalo (har page par GR No. likha ho). "
                "AI har page ka GR No. padhega, PDF ko GR-wise kaatega, aur har trip mein uski POD jod dega.")
    if not ai.configured():
        st.warning("AI key nahi hai — Streamlit Secrets mein GEMINI_API_KEY daalo.")
    if not drive.configured():
        st.warning("Google Drive juda nahi hai — kaati hui POD save karne ke liye Drive chahiye.")
    m = st.session_state.get("sp_n", 0)
    pdf = st.file_uploader("Scanned POD PDF (50–100 page tak ek baar mein)", type=["pdf"], key=f"sp_pdf_{m}")
    if pdf and st.button("🤖 GR-wise padho", type="primary", use_container_width=True, disabled=not ai.configured()):
        import io

        from pypdf import PdfReader
        try:
            n_pages = len(PdfReader(io.BytesIO(pdf.getvalue())).pages)
            with st.spinner(f"AI {n_pages} page padh raha hai... (1–2 minute)"):
                groups = ai.group_pages(ai.map_bundle(pdf.getvalue()), n_pages)
            st.session_state["sp_groups"] = groups
            st.session_state["sp_name"] = pdf.name
        except ai.AIError as e:
            st.error(str(e))
    groups = st.session_state.get("sp_groups")
    if pdf and groups:
        gr_map = {drive.match_key(t["gr_no"]): t
                  for t in trips.load_trips("not t.is_cancelled and t.gr_no is not null", None, "t.id")}
        import pandas as pd
        df = pd.DataFrame([{"Upload": bool(g["gr_no"]) and drive.match_key(g["gr_no"]) in gr_map,
                            "GR No.": g["gr_no"], "Pages": ", ".join(map(str, g["pages"])),
                            "Trip": (gr_map.get(drive.match_key(g["gr_no"])) or {}).get("trip_no", "❌ nahi mila"),
                            "Truck": (gr_map.get(drive.match_key(g["gr_no"])) or {}).get("truck_no", ""),
                            "AI sure": "✅" if g["sure"] else "⚠️ check"} for g in groups])
        st.caption("GR No. galat padha ho to table mein theek karo. '❌ nahi mila' = us GR ki trip nahi hai "
                   "(pehle trip mein GR No. bharo).")
        ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"sp_ed_{m}",
                            disabled=["Pages", "Trip", "Truck", "AI sure"],
                            column_config={"Upload": st.column_config.CheckboxColumn("✓")})
        todo = []
        for i, r in ed.iterrows():
            t = gr_map.get(drive.match_key(str(r["GR No."] or "")))
            if r["Upload"] and t:
                todo.append((t, groups[i]["pages"]))
        if st.button(f"⬆ {len(todo)} POD trips mein jodo", type="primary", use_container_width=True,
                     disabled=not todo or not drive.configured()):
            mark = db.setting_bool("pod_upload_marks_received")
            bar = st.progress(0.0)
            for k, (t, pages) in enumerate(todo, 1):
                part = ai.split_pdf(pdf.getvalue(), pages)
                drive.upload(t, "POD", f"POD_{t['gr_no']}.pdf", part, "application/pdf",
                             st.session_state.get("user", "admin"))
                if mark and not t["pod_received"]:
                    trips.update_trip(t["id"], {"pod_received": True, "pod_date": clock.today()})
                bar.progress(k / len(todo), text=f"{k}/{len(todo)}")
            st.session_state.pop("sp_groups", None)
            st.session_state["sp_n"] = m + 1
            ui.flash(f"{len(todo)} POD trips mein jud gayi")
            st.rerun()

if sel == SECTIONS[2]:
    st.markdown(
        "Upload many files at once. **File name = GR No.** — e.g. `4521.pdf`, `GR-4521.pdf`, "
        "`4521_POD.pdf`. The app finds the trip by GR No. and saves each file in that trip's Drive folder.\n\n"
        "Tip: scan all PODs together, split them GR-wise with an AI chat, then upload the split files here.")
    if not drive.configured():
        st.warning("Google Drive is not connected yet. See README → Google Drive setup.")
    default_type = st.radio("Document type (when the file name does not say POD)", ["POD", "GR", "OTHER"],
                            horizontal=True, key="bulk_type")
    n = st.session_state.get("bulk_n", 0)
    files = st.file_uploader("Choose files", accept_multiple_files=True,
                             type=["pdf", "jpg", "jpeg", "png", "webp"], key=f"bulk_files_{n}")
    if files:
        gr_map = {}
        for t in trips.load_trips("not t.is_cancelled and t.gr_no is not null", None, "t.id"):
            gr_map[drive.match_key(t["gr_no"])] = t
        plan, unmatched = [], []
        for f in files:
            gr = drive.gr_from_filename(f.name)
            t = gr_map.get(drive.match_key(gr))
            if t:
                plan.append((f, t, drive.doc_type_from_filename(f.name, default_type)))
            else:
                unmatched.append((f.name, gr))
        st.success(f"Matched: {len(plan)} file(s)")
        if plan:
            ui.show_table(ui.money_df(
                [{"file": f.name, "trip": t["trip_no"], "gr": t["gr_no"], "truck": t.get("truck_no"),
                  "party": t["party_name"], "type": dt, "already": t["all_docs"]} for f, t, dt in plan],
                {"file": "File", "trip": "Trip", "gr": "GR No.", "truck": "Truck", "party": "Party",
                 "type": "Type", "already": "Files already in trip"}), "bulk_plan")
        if unmatched:
            st.error(f"Not matched: {len(unmatched)} file(s) — check the GR No. in the file name, "
                     "or fill the GR No. in the trip first.")
            for name, gr in unmatched:
                st.write(f"• {name}  →  read as GR '{gr}'")
        if plan and st.button(f"Upload {len(plan)} matched file(s)", type="primary",
                              disabled=not drive.configured()):
            mark_pod = db.setting_bool("pod_upload_marks_received")
            bar = st.progress(0.0)
            done, pod_trips = 0, set()
            for f, t, dt in plan:
                drive.upload(t, dt, f.name, f.getvalue(), f.type, st.session_state.get("user", "admin"))
                if dt == "POD" and not t["pod_received"]:
                    pod_trips.add(t["id"])
                done += 1
                bar.progress(done / len(plan), text=f"{done}/{len(plan)} uploaded")
            if mark_pod:
                for tid in pod_trips:
                    trips.update_trip(tid, {"pod_received": True, "pod_date": clock.today()})
            st.session_state["bulk_n"] = n + 1
            st.success(f"{done} file(s) uploaded." + (f" {len(pod_trips)} trip(s) marked POD received." if mark_pod and pod_trips else ""))

if sel == SECTIONS[3]:
    rows = trips.load_trips("not t.is_cancelled and t.loaded_weight is not null", None, "t.loading_date")
    need = st.radio("Show trips without", ["POD copy", "GR copy", "GR No."], horizontal=True)
    if need == "POD copy":
        rows = [r for r in rows if not r["pod_docs"]]
    elif need == "GR copy":
        rows = [r for r in rows if not r["gr_docs"]]
    else:
        rows = [r for r in rows if not r.get("gr_no")]
    st.caption(f"{len(rows)} trips")
    ui.show_table(ui.money_df(rows, {"trip_no": "Trip", "loading_date": "Loaded", "gr_no": "GR No.",
                                     "truck_no": "Truck", "party_name": "Party", "from_place": "From",
                                     "to_place": "To", "pod_received": "POD received", "status": "Status"}),
                  "missing_docs", download_name="missing_documents")
