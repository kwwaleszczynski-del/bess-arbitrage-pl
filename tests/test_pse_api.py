from datetime import date, datetime, timezone

import pandas as pd
import pse_opendata as pse

from bess_arbitrage import pse_api

RECORDS = [
    {"dtime_utc": "2025-03-29 23:15:00", "rce_pln": "412.5", "business_date": "2025-03-30"},
    {"dtime_utc": "2025-03-29 23:30:00", "rce_pln": "-15.0", "business_date": "2025-03-30"},
]


class FakeResponse:
    def __init__(self, payload):
        self.status_code, self.headers, self.reason, self._payload = 200, {}, "OK", payload

    def json(self):
        return self._payload


class FakeSession:
    """Answers the business_date filters of pse-opendata from fixed records; records every call."""

    def __init__(self, records):
        self.records, self.calls = records, []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params))
        lo, hi = [part.split("'")[1] for part in params["$filter"].split(" and ")]
        return FakeResponse({"value": [r for r in self.records if lo <= r["business_date"] <= hi]})


def client(session, cache_dir):
    return pse.Client(session=session, cache_dir=cache_dir, now=lambda: datetime(2025, 6, 1, tzinfo=timezone.utc),
                      sleep=lambda s: None, min_interval=0, retries=1)


def test_fetch_range_uses_interval_start_in_utc(tmp_path):
    df = pse_api.fetch_range("rce", date(2025, 3, 30), date(2025, 3, 30), tmp_path,
                             client=client(FakeSession(RECORDS), tmp_path))
    assert df.index[0] == pd.Timestamp("2025-03-29 23:00", tz="UTC") and df.index.name == "ts_utc"
    assert df["price"].tolist() == [412.5, -15.0]
    assert df["business_date"].iloc[0] == date(2025, 3, 30)


def test_fetch_range_requests_whole_months_and_cuts(tmp_path):
    records = [{"dtime_utc": f"2025-03-{d:02d} 10:00:00", "csdac_pln": d, "business_date": f"2025-03-{d:02d}"}
               for d in range(1, 32)]
    session = FakeSession(records)
    df = pse_api.fetch_range("sdac", date(2025, 3, 10), date(2025, 3, 11), tmp_path, client=client(session, tmp_path))
    url, params = session.calls[0]
    assert url.endswith("/csdac-pln")
    assert params["$filter"] == "business_date ge '2025-03-01' and business_date le '2025-03-31'"
    assert df["price"].tolist() == [10.0, 11.0]
    assert (tmp_path / "api" / "csdac-pln" / "2025-03.parquet").exists()


def test_fetch_range_empty(tmp_path):
    df = pse_api.fetch_range("rce", date(2025, 3, 1), date(2025, 3, 31), tmp_path,
                             client=client(FakeSession([]), tmp_path))
    assert df.empty and list(df.columns) == ["price", "business_date"]
