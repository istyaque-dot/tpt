"""Remembered-login key: valid 30 days, can't be forged, dies when the password changes."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "streamlit" not in sys.modules:                       # tests run without Streamlit installed
    sys.modules["streamlit"] = types.ModuleType("streamlit")
st = sys.modules["streamlit"]
st.secrets = {"APP_PASSWORD": "p"}
from core import ui  # noqa: E402


def test_login_key():
    k = ui.make_login_key(now=1_000_000)
    assert ui.check_login_key(k, now=1_000_000 + 86400 * 29)
    assert not ui.check_login_key(k, now=1_000_000 + 86400 * 31)
    assert not ui.check_login_key(k[:-1] + ("0" if k[-1] != "0" else "1"), now=1_000_100)
    assert not ui.check_login_key("junk") and not ui.check_login_key(None)
    st.secrets["APP_PASSWORD"] = "changed"
    assert not ui.check_login_key(k, now=1_000_100)
    st.secrets["APP_PASSWORD"] = "p"


if __name__ == "__main__":
    test_login_key()
    print("login tests passed")
