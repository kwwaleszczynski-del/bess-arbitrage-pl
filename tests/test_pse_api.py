from datetime import date

import pandas as pd

from bess_arbitrage import pse_api

RECORDS = [
    {"dtime_utc": "2025-03-29 23:15:00", "rce_pln": "412.5", "business_date": "2025-03-30"},
    {"dtime_utc": "2025-03-29 23:30:00", "rce_pln": "-15.0", "business_date": "2025-03-30"},
]


def test_parse_records_uses_interval_start_in_utc():
    df = pse_api.parse_records(RECORDS, "rce_pln")
    assert df.index[0] == pd.Timestamp("2025-03-29 23:00", tz="UTC")
    assert df["price"].tolist() == [412.5, -15.0]
    assert df["business_date"].iloc[0] == date(2025, 3, 30)


def test_parse_empty():
    assert pse_api.parse_records([], "rce_pln").empty


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """Two pages: first with a nextLink, second without."""

    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        if len(self.calls) == 1:
            return FakeResponse({"value": RECORDS[:1], "nextLink": "https://api.raporty.pse.pl/api/next"})
        return FakeResponse({"value": RECORDS[1:]})


def test_fetch_period_follows_pagination():
    session = FakeSession()
    df = pse_api.fetch_period("rce", date(2025, 3, 30), date(2025, 3, 30), session=session)
    assert len(session.calls) == 2
    assert len(df) == 2
