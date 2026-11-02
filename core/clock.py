"""India time. Streamlit Cloud servers run on UTC, so date.today() there is still 'yesterday'
between 00:00 and 05:30 IST. Always use clock.today() in this app."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def today() -> date:
    return datetime.now(IST).date()


def now() -> datetime:
    return datetime.now(IST)
