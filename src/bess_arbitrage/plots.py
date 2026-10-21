"""Static charts (PNG) for the README.

Usage:
    from bess_arbitrage import plots
    plots.price_heatmap(prices, Path("docs/img/price_heatmap.png"))
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

TZ = "Europe/Warsaw"
COLORS = {"1h": "#4C78A8", "2h": "#F58518", "4h": "#54A24B", "price": "#555555", "charge": "#4C78A8", "discharge": "#E45756"}


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def price_heatmap(prices: pd.DataFrame, path: Path):
    """Average price by local hour of day and month - shows the solar 'duck curve'."""
    local = prices["price"].tz_convert(TZ)
    naive = local.index.tz_localize(None)  # periods carry no time zone; local wall-clock months are wanted here
    table = local.groupby([naive.to_period("M"), naive.hour]).mean().unstack()
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(table.T.values, aspect="auto", cmap="RdYlBu_r", origin="lower")
    ax.set_xticks(range(0, len(table.index), 3), [str(m) for m in table.index[::3]], rotation=45, ha="right")
    ax.set_ylabel("Hour of day (local time)")
    ax.set_title("Average price by hour and month [PLN/MWh]")
    fig.colorbar(im, ax=ax)
    _save(fig, path)


def monthly_revenue(results: dict[str, pd.DataFrame], power_mw: float, path: Path):
    """Monthly arbitrage revenue per MW for several durations."""
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for label, daily in results.items():
        m = daily["revenue_pln"].groupby(pd.to_datetime(daily.index).to_period("M")).sum() / power_mw / 1000
        ax.plot(m.index.to_timestamp(), m.values, marker="o", ms=3, label=label, color=COLORS.get(label))
    ax.set_ylabel("Revenue [thousand PLN / MW / month]")
    ax.set_title("Day-ahead arbitrage revenue (perfect foresight, net of degradation cost)")
    ax.grid(alpha=0.3)
    ax.legend(title="Duration")
    _save(fig, path)


def negative_prices(monthly: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.bar(monthly.index.to_timestamp(), monthly["negative_intervals"] / 4, width=20, color="#E45756")
    ax.set_ylabel("Hours with negative price")
    ax.set_title("Negative-price hours per month")
    ax.grid(axis="y", alpha=0.3)
    _save(fig, path)


def example_day(schedule: pd.DataFrame, title: str, path: Path):
    """Price, charge/discharge and state of charge on one day."""
    s = schedule.tz_convert(TZ) if schedule.index.tz is not None else schedule
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, height_ratios=[1.2, 1])
    ax1.step(s.index, s["price"], where="post", color=COLORS["price"])
    ax1.set_ylabel("Price [PLN/MWh]")
    ax1.set_title(title)
    ax1.grid(alpha=0.3)
    ax2.bar(s.index, -s["charge_mw"], width=0.01, align="edge", color=COLORS["charge"], label="charge")
    ax2.bar(s.index, s["discharge_mw"], width=0.01, align="edge", color=COLORS["discharge"], label="discharge")
    ax2.set_ylabel("Power [MW]")
    ax3 = ax2.twinx()
    ax3.plot(s.index, s["soc_mwh"], color="black", lw=1.2, label="state of charge")
    ax3.set_ylabel("SoC [MWh]")
    ax2.legend(loc="upper left")
    ax2.grid(alpha=0.3)
    _save(fig, path)
