"""Day-by-day backtest of the arbitrage optimiser over a price history, plus market statistics.

Usage:
    from bess_arbitrage.backtest import run_backtest, price_stats
    daily = run_backtest(prices, BatteryParams(power_mw=1, energy_mwh=2))
"""
from __future__ import annotations

import logging
from dataclasses import asdict

import pandas as pd

from bess_arbitrage.optimizer import BatteryParams, optimize_day

log = logging.getLogger(__name__)


def run_backtest(prices: pd.DataFrame, params: BatteryParams, keep_schedules: bool = False):
    """Optimise every complete delivery day independently. Returns daily results (and schedules if asked)."""
    rows, schedules = [], {}
    for day, grp in prices.groupby("business_date"):
        p = grp["price"]
        if p.isna().any() or len(p) < 92:
            log.debug("skip %s: %d intervals, %d missing", day, len(p), p.isna().sum())
            continue
        res = optimize_day(p, params)
        s = res.schedule
        bought = (s["charge_mw"] * 0.25).sum()
        rows.append({
            "date": day,
            "revenue_pln": res.revenue,
            "gross_revenue_pln": res.gross_revenue,
            "discharged_mwh": res.discharged_mwh,
            "cycles": res.cycles,
            "avg_buy_price": (s["price"] * s["charge_mw"]).sum() * 0.25 / bought if bought else float("nan"),
            "avg_sell_price": (s["price"] * s["discharge_mw"]).sum() * 0.25 / res.discharged_mwh if res.discharged_mwh else float("nan"),
            "spread_max_min": p.max() - p.min(),
        })
        if keep_schedules:
            schedules[day] = s
    daily = pd.DataFrame(rows).set_index("date")
    daily.attrs["params"] = asdict(params)
    return (daily, schedules) if keep_schedules else daily


def summarize(daily: pd.DataFrame, params: BatteryParams) -> dict:
    """Annualised key figures per MW of power."""
    days = len(daily)
    per_year = 365.0 / days if days else 0.0
    return {
        "duration_h": params.energy_mwh / params.power_mw,
        "rte": params.round_trip_efficiency,
        "max_cycles": params.max_cycles_per_day,
        "degradation_cost": params.degradation_cost,
        "days": days,
        "revenue_pln_per_mw_year": daily["revenue_pln"].sum() * per_year / params.power_mw,
        "revenue_pln_per_mwh_year": daily["revenue_pln"].sum() * per_year / params.energy_mwh,
        "avg_cycles_per_day": daily["cycles"].mean(),
        "share_days_no_trade": float((daily["discharged_mwh"] < 1e-6).mean()),
    }


def price_stats(prices: pd.DataFrame) -> pd.DataFrame:
    """Monthly market statistics: mean price, daily spread, negative-price intervals."""
    df = prices.copy()
    df["month"] = pd.to_datetime(df["business_date"]).dt.to_period("M")
    daily = df.groupby("business_date").agg(spread=("price", lambda x: x.max() - x.min()), month=("month", "first"))
    monthly = df.groupby("month").agg(mean_price=("price", "mean"), min_price=("price", "min"), max_price=("price", "max"),
                                      negative_intervals=("price", lambda x: int((x < 0).sum())))
    monthly["mean_daily_spread"] = daily.groupby("month")["spread"].mean()
    return monthly
