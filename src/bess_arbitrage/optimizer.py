"""Daily price-arbitrage dispatch of a battery as a mixed-integer linear program (HiGHS via scipy).

For one delivery day with known prices p_t (PLN/MWh, interval length dt hours) the battery chooses
charge c_t and discharge d_t (MW) to maximise

    sum_t p_t * dt * (d_t - c_t)  -  deg_cost * sum_t dt * d_t

subject to
    soc_t = soc_{t-1} + eta_c * dt * c_t - dt * d_t / eta_d        (energy balance, MWh)
    soc_min <= soc_t <= soc_max,  soc_end = soc_start                (no free energy across days)
    0 <= c_t <= P * u_t,  0 <= d_t <= P * (1 - u_t),  u_t binary     (no simultaneous charge/discharge)
    sum_t dt * d_t <= max_cycles * usable_energy                     (warranty-style throughput cap)

Perfect foresight of day-ahead prices is realistic for the day-ahead market (prices are known the day
before delivery), so the result is an upper bound for a pure day-ahead arbitrage strategy.

Usage:
    from bess_arbitrage import BatteryParams, optimize_day
    res = optimize_day(prices_pln_mwh, BatteryParams(power_mw=1, energy_mwh=2))
    res.revenue, res.schedule
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, milp


@dataclass(frozen=True)
class BatteryParams:
    power_mw: float = 1.0
    energy_mwh: float = 2.0
    round_trip_efficiency: float = 0.87
    soc_min: float = 0.05          # fraction of energy_mwh
    soc_max: float = 0.95
    soc_start: float = 0.5         # also required at the end of each day
    max_cycles_per_day: float = 1.5
    degradation_cost: float = 30.0  # PLN per MWh discharged

    @property
    def usable_mwh(self) -> float:
        return self.energy_mwh * (self.soc_max - self.soc_min)

    @property
    def eta(self) -> float:
        """One-way efficiency, split symmetrically between charging and discharging."""
        return float(np.sqrt(self.round_trip_efficiency))


@dataclass
class DispatchResult:
    revenue: float                 # PLN, net of degradation cost
    gross_revenue: float           # PLN, energy only
    discharged_mwh: float
    cycles: float
    schedule: pd.DataFrame         # charge_mw, discharge_mw, soc_mwh, price


def optimize_day(prices: pd.Series | np.ndarray, params: BatteryParams, dt_hours: float = 0.25) -> DispatchResult:
    """Solve the arbitrage MILP for one day of prices (any length, e.g. 92/96/100 intervals on DST days)."""
    p = np.asarray(prices, dtype=float)
    if np.isnan(p).any():
        raise ValueError("prices contain NaN")
    n = len(p)
    eta, P = params.eta, params.power_mw
    e_min, e_max = params.energy_mwh * params.soc_min, params.energy_mwh * params.soc_max
    soc0 = params.energy_mwh * params.soc_start

    # variable layout: [charge(n), discharge(n), soc(n), u(n)]
    ic, idd, isoc, iu = 0, n, 2 * n, 3 * n
    nv = 4 * n
    cost = np.zeros(nv)
    cost[ic:ic + n] = p * dt_hours
    cost[idd:idd + n] = -(p - params.degradation_cost) * dt_hours

    eye = sparse.identity(n, format="csr")
    shift = sparse.eye(n, k=-1, format="csr")          # soc_{t-1}
    zeros = sparse.csr_matrix((n, n))
    # energy balance: soc_t - soc_{t-1} - eta*dt*c_t + dt/eta*d_t = (soc0 if t == 0 else 0)
    balance = sparse.hstack([-eta * dt_hours * eye, (dt_hours / eta) * eye, eye - shift, zeros])
    rhs = np.zeros(n)
    rhs[0] = soc0
    # end-of-day state of charge equals the start
    end_row = sparse.csr_matrix(([1.0], ([0], [isoc + n - 1])), shape=(1, nv))
    # c_t - P*u_t <= 0 ;  d_t + P*u_t <= P
    ch_mode = sparse.hstack([eye, zeros, zeros, -P * eye])
    dis_mode = sparse.hstack([zeros, eye, zeros, P * eye])
    # throughput cap
    thr_row = sparse.csr_matrix((np.full(n, dt_hours), (np.zeros(n, int), np.arange(idd, idd + n))), shape=(1, nv))

    constraints = [
        LinearConstraint(balance, rhs, rhs),
        LinearConstraint(end_row, soc0, soc0),
        LinearConstraint(ch_mode, -np.inf, 0.0),
        LinearConstraint(dis_mode, -np.inf, P),
        LinearConstraint(thr_row, 0.0, params.max_cycles_per_day * params.usable_mwh),
    ]
    lb = np.concatenate([np.zeros(2 * n), np.full(n, e_min), np.zeros(n)])
    ub = np.concatenate([np.full(2 * n, P), np.full(n, e_max), np.ones(n)])
    integrality = np.concatenate([np.zeros(3 * n), np.ones(n)])

    res = milp(cost, constraints=constraints, bounds=Bounds(lb, ub), integrality=integrality,
               options={"disp": False, "mip_rel_gap": 1e-6})
    if not res.success:
        raise RuntimeError(f"MILP failed: {res.message}")
    x = res.x
    charge, discharge, soc = x[ic:ic + n], x[idd:idd + n], x[isoc:isoc + n]
    charge[charge < 1e-9] = 0.0
    discharge[discharge < 1e-9] = 0.0
    index = prices.index if isinstance(prices, pd.Series) else pd.RangeIndex(n)
    schedule = pd.DataFrame({"price": p, "charge_mw": charge, "discharge_mw": discharge, "soc_mwh": soc}, index=index)
    gross = float(np.sum(p * dt_hours * (discharge - charge)))
    discharged = float(np.sum(discharge) * dt_hours)
    return DispatchResult(
        revenue=gross - params.degradation_cost * discharged,
        gross_revenue=gross,
        discharged_mwh=discharged,
        cycles=discharged / params.usable_mwh if params.usable_mwh else 0.0,
        schedule=schedule,
    )
