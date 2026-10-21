import numpy as np
import pytest

from bess_arbitrage import BatteryParams, optimize_day

LOSSLESS = BatteryParams(power_mw=1.0, energy_mwh=1.0, round_trip_efficiency=1.0, soc_min=0.0, soc_max=1.0,
                         soc_start=0.0, max_cycles_per_day=5.0, degradation_cost=0.0)


def test_flat_prices_do_nothing():
    res = optimize_day(np.full(96, 400.0), BatteryParams())
    assert res.discharged_mwh == pytest.approx(0.0, abs=1e-6)
    assert res.revenue == pytest.approx(0.0, abs=1e-6)


def test_buys_low_sells_high_lossless():
    prices = np.r_[np.full(48, 100.0), np.full(48, 600.0)]
    # a tiny degradation cost removes zero-profit cycling at equal prices, so the optimum is unique
    params = BatteryParams(**{**LOSSLESS.__dict__, "degradation_cost": 1.0})
    res = optimize_day(prices, params)
    # 1 MWh bought at 100 and sold at 600, limited by capacity and the end-of-day SoC rule
    assert res.gross_revenue == pytest.approx(500.0, rel=1e-6)
    assert res.revenue == pytest.approx(499.0, rel=1e-6)
    assert res.schedule["charge_mw"].iloc[48:].sum() == pytest.approx(0.0, abs=1e-9)
    assert res.schedule["discharge_mw"].iloc[:48].sum() == pytest.approx(0.0, abs=1e-9)


def test_efficiency_losses_reduce_revenue():
    prices = np.r_[np.full(48, 100.0), np.full(48, 600.0)]
    p = BatteryParams(power_mw=1, energy_mwh=1, round_trip_efficiency=0.81, soc_min=0, soc_max=1,
                      soc_start=0, max_cycles_per_day=5, degradation_cost=0)
    res = optimize_day(prices, p)
    # discharge 1 MWh usable -> sold 1 * 0.9 = 0.9 MWh, bought 1 / 0.9 = 1.111 MWh
    assert res.revenue == pytest.approx(600 * 0.9 - 100 / 0.9, rel=1e-4)


def test_constraints_hold():
    rng = np.random.default_rng(0)
    prices = rng.normal(500, 250, 96)
    params = BatteryParams(power_mw=1.0, energy_mwh=2.0, max_cycles_per_day=1.0)
    s = optimize_day(prices, params).schedule
    e = params.energy_mwh
    assert s["soc_mwh"].min() >= e * params.soc_min - 1e-6
    assert s["soc_mwh"].max() <= e * params.soc_max + 1e-6
    assert s["soc_mwh"].iloc[-1] == pytest.approx(e * params.soc_start, abs=1e-6)
    assert ((s["charge_mw"] > 1e-9) & (s["discharge_mw"] > 1e-9)).sum() == 0
    assert (s["discharge_mw"].sum() * 0.25) <= params.max_cycles_per_day * params.usable_mwh + 1e-6


def test_negative_prices_are_used_for_charging():
    prices = np.r_[np.full(32, -200.0), np.full(32, 300.0), np.full(32, 300.0)]
    res = optimize_day(prices, BatteryParams(round_trip_efficiency=0.9, degradation_cost=0))
    assert res.schedule["charge_mw"].iloc[:32].sum() > 0
    assert res.revenue > 0


def test_dst_day_lengths():
    for n in (92, 100):
        res = optimize_day(np.linspace(100, 700, n), BatteryParams())
        assert len(res.schedule) == n
        assert res.revenue > 0


def test_nan_prices_rejected():
    with pytest.raises(ValueError):
        optimize_day(np.r_[np.full(95, 100.0), np.nan], BatteryParams())
