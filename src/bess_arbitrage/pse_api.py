"""Polish 15-minute price series, read with the pse-opendata client (https://pypi.org/project/pse-opendata/).

pse-opendata downloads the public PSE reports API (https://api.raporty.pse.pl, no key) and caches whole months as
Parquet files in ``cache_dir`` (``api/<report>/<YYYY-MM>.parquet``); a month is downloaded again until three days
after its end (the revision window of prices).

Series:
    rce   - RCE, "rynkowa cena energii" (market price used e.g. for prosumer settlement), PLN/MWh
    sdac  - day-ahead price from the single day-ahead coupling (SDAC) for the Polish zone, PLN/MWh

Usage:
    from bess_arbitrage.pse_api import fetch_range
    prices = fetch_range("rce", date(2024, 7, 1), date(2024, 12, 31), cache_dir=Path("data"))
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pse_opendata as pse

SERIES = {"rce": ("rce-pln", "rce_pln"), "sdac": ("csdac-pln", "csdac_pln")}
log = logging.getLogger(__name__)


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["price", "business_date"]).rename_axis("ts_utc")


def fetch_range(series: str, start: date, end: date, cache_dir: Path, refresh: bool = False,
                client: pse.Client | None = None) -> pd.DataFrame:
    """One series for business dates start..end (inclusive): columns price and business_date, index ts_utc (UTC
    interval start).

    Whole months are requested, so that pse-opendata caches them; ``refresh`` downloads again months the cache holds
    as final. Intervals without a price are kept; a repeated interval keeps its last row.
    """
    endpoint, field = SERIES[series]
    client = client or pse.Client(cache_dir=cache_dir, refresh=refresh)
    loaded = len(client.loads)
    raw = client.get(endpoint, date(start.year, start.month, 1), (pd.Timestamp(end) + pd.offsets.MonthEnd(0)).date(),
                     fields=[field])
    for load in client.loads[loaded:]:
        log.info("%s %s: %d intervals (%s)", series, f"{load.month:%Y-%m}", load.rows, load.status)
    raw = raw[(raw["business_date"] >= start) & (raw["business_date"] <= end)]
    if raw.empty:
        return empty_frame()
    return pd.DataFrame({"price": raw[field].to_numpy(), "business_date": raw["business_date"].to_numpy()},
                        index=pd.DatetimeIndex(raw["start_utc"], name="ts_utc"))
