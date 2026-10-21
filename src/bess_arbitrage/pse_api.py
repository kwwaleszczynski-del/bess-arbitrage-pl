"""Client for the public PSE reports API (https://api.raporty.pse.pl).

Downloads 15-minute price series for the Polish market and caches them as monthly Parquet files.

Series:
    rce   - RCE, "rynkowa cena energii" (market price used e.g. for prosumer settlement), PLN/MWh
    sdac  - day-ahead price from the single day-ahead coupling (SDAC) for the Polish zone, PLN/MWh

Usage:
    from bess_arbitrage.pse_api import fetch_range
    prices = fetch_range("rce", date(2024, 7, 1), date(2024, 12, 31), cache_dir=Path("data"))
"""
from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://api.raporty.pse.pl/api"
SERIES = {"rce": ("rce-pln", "rce_pln"), "sdac": ("csdac-pln", "csdac_pln")}
INTERVAL = pd.Timedelta("15min")
log = logging.getLogger(__name__)


def parse_records(records: list[dict], value_field: str) -> pd.DataFrame:
    """Turn API records into a frame indexed by interval START in UTC.

    The API's ``dtime_utc`` is the END of the 15-minute interval ("00:00 - 00:15" -> dtime 00:15).
    """
    if not records:
        return pd.DataFrame(columns=["price", "business_date"]).rename_axis("ts_utc")
    df = pd.DataFrame.from_records(records)
    out = pd.DataFrame({
        "ts_utc": pd.to_datetime(df["dtime_utc"]).dt.tz_localize("UTC") - INTERVAL,
        "price": pd.to_numeric(df[value_field], errors="coerce"),
        "business_date": pd.to_datetime(df["business_date"]).dt.date,
    })
    return out.drop_duplicates("ts_utc").set_index("ts_utc").sort_index()


def _get(session: requests.Session, url: str, params: dict | None = None, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.warning("PSE API request failed (%s), retrying", e)
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def fetch_period(series: str, start: date, end: date, session: requests.Session | None = None) -> pd.DataFrame:
    """Fetch one series for business dates start..end (inclusive), following pagination links."""
    endpoint, field = SERIES[series]
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "bess-arbitrage-pl (open-source analysis)")
    params = {
        "$filter": f"business_date ge '{start:%Y-%m-%d}' and business_date le '{end:%Y-%m-%d}'",
        "$select": f"dtime_utc,{field},business_date",
        "$first": 20000,
    }
    payload = _get(session, f"{BASE_URL}/{endpoint}", params)
    records = list(payload.get("value", []))
    while payload.get("nextLink"):
        payload = _get(session, payload["nextLink"])
        records += payload.get("value", [])
    return parse_records(records, field)


def fetch_range(series: str, start: date, end: date, cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    """Fetch start..end month by month; complete past months are cached as Parquet."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    frames = []
    for month_start in pd.date_range(date(start.year, start.month, 1), end, freq="MS"):
        m_start = max(month_start.date(), start)
        m_end = min((month_start + pd.offsets.MonthEnd(0)).date(), end)
        cache = cache_dir / f"{series}_{month_start:%Y-%m}.parquet"
        complete = (month_start + pd.offsets.MonthEnd(0)).date() < date.today()
        if cache.exists() and not refresh and complete:
            df = pd.read_parquet(cache)
        else:
            df = fetch_period(series, m_start, m_end, session)
            if complete and m_start == month_start.date():
                df.to_parquet(cache)
            log.info("%s %s: %d intervals", series, f"{month_start:%Y-%m}", len(df))
        frames.append(df[(df["business_date"] >= m_start) & (df["business_date"] <= m_end)])
    return pd.concat(frames).sort_index() if frames else parse_records([], "price")
