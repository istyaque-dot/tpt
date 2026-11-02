"""Typed truck numbers: find old truck (full / last digits), create new truck + owner once."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "streamlit" not in sys.modules:
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    st.cache_resource = st.cache_data
    st.secrets = {}
    sys.modules["streamlit"] = st
for m in ("psycopg2", "psycopg2.extras", "psycopg2.pool"):
    sys.modules.setdefault(m, types.ModuleType(m))
from core import trips  # noqa: E402

TRUCKS = [{"id": 1, "truck_no": "RJ14AB1234"}, {"id": 2, "truck_no": "RJ14CD5678"}, {"id": 3, "truck_no": "MH12EF5678"}]


class FakeCur:
    def __init__(self):
        self.trucks, self.owners, self.sql = {}, {}, []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self._last = (sql, params)

    def fetchone(self):
        sql, p = self._last
        if sql.startswith("select id from trucks"):
            return {"id": self.trucks[p[0]]} if p[0] in self.trucks else None
        if sql.startswith("insert into accounts"):
            self.owners.setdefault(p[0], 100 + len(self.owners))
            return {"id": self.owners[p[0]]}
        if sql.startswith("insert into trucks"):
            self.trucks[p[0]] = 200 + len(self.trucks)
            return {"id": self.trucks[p[0]]}


def test_find_truck():
    assert trips.find_truck("rj 14 ab 1234", TRUCKS)["id"] == 1
    assert trips.find_truck("1234", TRUCKS)["id"] == 1            # unique last digits
    assert trips.find_truck("5678", TRUCKS) is None               # two trucks end in 5678
    assert trips.find_truck("GJ01XY0001", TRUCKS) is None
    assert trips.looks_like_truck_no("gj 01 xy 0001") and not trips.looks_like_truck_no("5678")


def test_resolve_creates_once():
    cur = FakeCur()
    a = trips.resolve_truck(cur, "gj01xy0001", "")
    b = trips.resolve_truck(cur, "GJ 01 XY 0001", "Ramesh")
    assert a == b and list(cur.trucks) == ["GJ01XY0001"]
    assert "GJ01XY0001" in cur.owners                               # blank owner -> named after truck
    trips.resolve_truck(cur, "UP15AA1111", "Suresh")
    assert "Suresh" in cur.owners


if __name__ == "__main__":
    test_find_truck()
    test_resolve_creates_once()
    print("truck resolve tests passed")
