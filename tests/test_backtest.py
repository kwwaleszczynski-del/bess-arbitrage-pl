import pandas as pd
import pytest

from bess_arbitrage import BatteryParams
from bess_arbitrage.backtest import yearly


def test_yearly_sums_revenue_and_weights_prices_by_energy():
    daily = pd.DataFrame({
        "revenue_pln": [100.0, 300.0, 50.0],
        "discharged_mwh": [1.0, 3.0, 0.0],
        "avg_buy_price": [100.0, 200.0, float("nan")],
        "avg_sell_price": [500.0, 700.0, float("nan")],
        "spread_max_min": [400.0, 600.0, 200.0],
    }, index=pd.Index(["2025-12-31", "2026-01-01", "2026-01-02"], name="date"))
    out = yearly(daily, BatteryParams(power_mw=2.0, energy_mwh=4.0))
    assert list(out.index) == [2025, 2026]
    assert out.loc[2026, "days"] == 2
    assert out.loc[2026, "revenue_pln_per_mw"] == pytest.approx(175.0)
    assert out.loc[2026, "mean_daily_spread"] == pytest.approx(400.0)
    assert out.loc[2026, "avg_buy_price"] == pytest.approx(200.0)
    assert out.loc[2026, "avg_sell_price"] == pytest.approx(700.0)
    assert (out["duration_h"] == 2.0).all()
