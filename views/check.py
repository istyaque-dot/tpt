"""Hisaab Check: one button re-checks the whole logic and books."""
import pandas as pd
import streamlit as st

from core import checks, db, trips, ui

st.markdown("### 🧮 Hisaab Check")
st.caption("App saara hisaab shuru se dobara calculate karke books se milata hai. Kuch galat ho toh yahan dikhega.")

if st.button("▶ Run all checks", type="primary", use_container_width=True) or st.session_state.get("chk_ran"):
    st.session_state["chk_ran"] = True
    with st.spinner("Checking..."):
        results = checks.run_all()
    ok_n = sum(1 for r in results if r[1])
    (st.success if ok_n == len(results) else st.warning)(f"{ok_n} / {len(results)} checks OK")
    for title, ok, why, rows in results:
        with st.expander(f"{'✅' if ok else '⚠️'} {title}" + ("" if ok else f" — {len(rows)}"), expanded=not ok):
            st.caption(why)
            if rows:
                df = pd.DataFrame([{k: (float(v) if hasattr(v, "quantize") else v) for k, v in r.items() if k != "id"}
                                   for r in rows])
                ui.show_table(df, f"chk_{title[:20]}")
            if title.startswith("Trip bills") and rows:
                if st.button(f"🔧 Rebuild these {len(rows)} trip bills from trip details", key="chk_fix"):
                    with db.tx() as cur:
                        for r in rows:
                            trips.repost_trip(cur, r["id"])
                    ui.flash(f"{len(rows)} trip bill(s) rebuilt")
                    st.rerun()

st.divider()
st.markdown("#### Check one trip")
q = st.text_input("Trip No. / truck / GR", key="chk_q", placeholder="Type to search")
if q.strip():
    found = trips.find_trips(q, "All", 10)
    for t in found:
        with st.expander(f"{t['trip_no']} · {t.get('truck_no') or ''} · GR {t.get('gr_no') or '—'} · {t['status']}"):
            rows = checks.trip_check(t)
            ok = all(r["OK"] == "✅" for r in rows)
            (st.success if ok else st.error)("Formula aur books match." if ok else "Mismatch mila.")
            ui.show_table(pd.DataFrame(rows), f"chk_trip_{t['id']}", money_cols=["Should be", "In books"])
