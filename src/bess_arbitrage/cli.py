"""Command line interface.

Usage:
    python -m bess_arbitrage fetch  --series rce --start 2024-06-14 --end 2026-10-20
    python -m bess_arbitrage run    --series rce --start 2024-06-14 --end 2026-10-20 --durations 1 2 4
    python -m bess_arbitrage run    --help

Data are cached in ./data (override with --data-dir or BESS_DATA_DIR), results go to ./results and charts to ./docs/img.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path

import pandas as pd

from bess_arbitrage import plots
from bess_arbitrage.backtest import price_stats, run_backtest, summarize
from bess_arbitrage.optimizer import BatteryParams
from bess_arbitrage.pse_api import SERIES, fetch_range

log = logging.getLogger("bess_arbitrage")


def _date(s: str) -> date:
    return date.fromisoformat(s)


def cmd_fetch(args) -> pd.DataFrame:
    prices = fetch_range(args.series, args.start, args.end, args.data_dir, refresh=args.refresh)
    log.info("%s: %d intervals, %d days, %s .. %s", args.series, len(prices), prices["business_date"].nunique(),
             prices.index.min(), prices.index.max())
    return prices


def cmd_run(args):
    prices = cmd_fetch(args)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    monthly = price_stats(prices)
    monthly.to_csv(args.results_dir / f"{args.series}_monthly_stats.csv")

    results, summaries = {}, []
    for dur in args.durations:
        params = BatteryParams(power_mw=args.power, energy_mwh=args.power * dur, round_trip_efficiency=args.rte,
                               max_cycles_per_day=args.cycles, degradation_cost=args.deg_cost)
        daily, schedules = run_backtest(prices, params, keep_schedules=True)
        label = f"{dur:g}h"
        results[label] = daily
        daily.to_csv(args.results_dir / f"{args.series}_daily_{label}.csv")
        summaries.append(summarize(daily, params))
        log.info("%s: %.0f PLN/MW/year over %d days", label, summaries[-1]["revenue_pln_per_mw_year"], len(daily))
        if dur == 2:
            best_day = daily["revenue_pln"].idxmax()
            plots.example_day(schedules[best_day], f"Best day {best_day} - 2 h battery", args.img_dir / "example_day.png")

    # sensitivity of the 2 h battery to efficiency and cycle cap
    sens = []
    for rte in (0.80, 0.87, 0.92):
        for cycles in (1.0, 1.5, 2.0):
            params = BatteryParams(power_mw=args.power, energy_mwh=2 * args.power, round_trip_efficiency=rte,
                                   max_cycles_per_day=cycles, degradation_cost=args.deg_cost)
            sens.append(summarize(run_backtest(prices, params), params))
    pd.DataFrame(summaries).to_csv(args.results_dir / f"{args.series}_summary.csv", index=False)
    pd.DataFrame(sens).to_csv(args.results_dir / f"{args.series}_sensitivity_2h.csv", index=False)

    plots.price_heatmap(prices, args.img_dir / "price_heatmap.png")
    plots.monthly_revenue(results, args.power, args.img_dir / "monthly_revenue.png")
    plots.negative_prices(monthly, args.img_dir / "negative_prices.png")
    (args.results_dir / "run.json").write_text(json.dumps(
        {"series": args.series, "start": str(args.start), "end": str(args.end), "summary": summaries}, indent=2, default=str))
    log.info("results in %s, charts in %s", args.results_dir, args.img_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bess-arbitrage", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "run"):
        p = sub.add_parser(name)
        p.add_argument("--series", choices=SERIES, default="rce")
        p.add_argument("--start", type=_date, default=date(2024, 6, 14))
        p.add_argument("--end", type=_date, default=date.today())
        p.add_argument("--data-dir", type=Path, default=Path(os.environ.get("BESS_DATA_DIR", "data")))
        p.add_argument("--refresh", action="store_true", help="re-download cached months")
        if name == "run":
            p.add_argument("--power", type=float, default=1.0, help="MW")
            p.add_argument("--durations", type=float, nargs="+", default=[1, 2, 4], help="hours")
            p.add_argument("--rte", type=float, default=0.87, help="round-trip efficiency")
            p.add_argument("--cycles", type=float, default=1.5, help="max full cycles per day")
            p.add_argument("--deg-cost", type=float, default=30.0, help="PLN per MWh discharged")
            p.add_argument("--results-dir", type=Path, default=Path("results"))
            p.add_argument("--img-dir", type=Path, default=Path("docs/img"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    {"fetch": cmd_fetch, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
