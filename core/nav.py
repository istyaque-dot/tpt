"""Page registry so screens can jump to each other (filled by app.py on every run)."""
import streamlit as st

PAGES: dict = {}


def go(name: str, **state):
    """Switch page, optionally setting session values first (e.g. open_trip_id=12)."""
    st.session_state.update(state)
    st.switch_page(PAGES[name])


def open_trip(trip_id: int):
    go("trips", open_trip_id=trip_id)
