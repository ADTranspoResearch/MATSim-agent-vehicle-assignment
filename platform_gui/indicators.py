"""FSA indicators used in the paper (Section 3.4.3 and Table 5).

All functions take numpy arrays aligned on the same FSA order. Units:
CO2 in kt/year, electricity in GWh/year, area in km2, agents as the expanded
count (MATSim 10% sample times ten), matching ``fsa_results.csv``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

DAYS_PER_YEAR = 365
CHARGING_WINDOWS_H = (4, 6, 8, 24)


def ev_share(n_ev, n_vehicles):
    n_ev = np.asarray(n_ev, dtype=float)
    n_vehicles = np.asarray(n_vehicles, dtype=float)
    return np.divide(n_ev, n_vehicles, out=np.zeros_like(n_ev), where=n_vehicles > 0)


def co2_per_agent_kg(co2_kt, agents):
    """Tailpipe kg CO2 per automobile agent per year."""
    co2_kt = np.asarray(co2_kt, dtype=float)
    agents = np.asarray(agents, dtype=float)
    return np.divide(co2_kt * 1e6, agents, out=np.zeros_like(co2_kt), where=agents > 0)


def kwh_per_agent(gwh, agents):
    gwh = np.asarray(gwh, dtype=float)
    agents = np.asarray(agents, dtype=float)
    return np.divide(gwh * 1e6, agents, out=np.zeros_like(gwh), where=agents > 0)


def added_electricity_gwh(gwh, ref_gwh):
    return np.asarray(gwh, dtype=float) - np.asarray(ref_gwh, dtype=float)


def kappa_g_per_kwh(ref_co2_kt, co2_kt, ref_gwh, gwh):
    """Average electrification effectiveness (Eq. 17), g CO2 avoided per added kWh.

    NaN where no electricity is added, because the ratio is undefined there.
    """
    avoided_g = (np.asarray(ref_co2_kt, dtype=float) - np.asarray(co2_kt, dtype=float)) * 1e9
    added_kwh = added_electricity_gwh(gwh, ref_gwh) * 1e6
    out = np.full_like(avoided_g, np.nan, dtype=float)
    np.divide(avoided_g, added_kwh, out=out, where=added_kwh > 0)
    return out


def density_mwh_per_km2(added_gwh, area_km2):
    added_gwh = np.asarray(added_gwh, dtype=float)
    area_km2 = np.asarray(area_km2, dtype=float)
    out = np.full_like(added_gwh, np.nan, dtype=float)
    np.divide(added_gwh * 1e3, area_km2, out=out, where=area_km2 > 0)
    return out


def load_mw(added_gwh, window_hours: float):
    """Mean added charging load if the daily requirement is spread over a window."""
    return np.asarray(added_gwh, dtype=float) * 1e3 / (DAYS_PER_YEAR * window_hours)


def concentration_curve(values) -> dict[str, list[float]]:
    """Cumulative share of a total held by the top-n FSAs, largest first."""
    values = np.sort(np.asarray(values, dtype=float)[np.isfinite(values)])[::-1]
    total = values.sum()
    if total <= 0:
        return {"fsa_share": [], "value_share": []}
    count = len(values)
    return {
        "fsa_share": [(index + 1) / count for index in range(count)],
        "value_share": (np.cumsum(values) / total).tolist(),
    }


def top_share(values, k: int) -> float:
    values = np.sort(np.asarray(values, dtype=float))[::-1]
    total = values.sum()
    return float(values[:k].sum() / total) if total > 0 else 0.0


def fsas_for_half(values) -> int:
    values = np.sort(np.asarray(values, dtype=float))[::-1]
    total = values.sum()
    if total <= 0:
        return 0
    return int(np.searchsorted(np.cumsum(values) / total, 0.5) + 1)


def pearson(x, y) -> dict[str, float]:
    """Pearson r with a Fisher-z 95% interval and a normal-approximation p value."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    n = len(x)
    if n < 4 or x.std() == 0 or y.std() == 0:
        return {"r": float("nan"), "lo": float("nan"), "hi": float("nan"), "p": float("nan"), "n": n}
    r = float(np.corrcoef(x, y)[0, 1])
    r = max(min(r, 0.999999), -0.999999)
    z = math.atanh(r)
    se = 1 / math.sqrt(n - 3)
    p = math.erfc(abs(z) / se / math.sqrt(2))
    return {
        "r": r,
        "lo": math.tanh(z - 1.96 * se),
        "hi": math.tanh(z + 1.96 * se),
        "p": p,
        "n": n,
    }


def citywide_summary(
    co2_kt: float,
    gwh: float,
    n_ev: float,
    n_vehicles: float,
    agents: float,
    ref: dict[str, float] | None,
) -> dict[str, Any]:
    """One column of the paper's Table 5."""
    row: dict[str, Any] = {
        "co2_kt": co2_kt,
        "co2_kg_per_agent": co2_kt * 1e6 / agents if agents else 0.0,
        "electricity_gwh": gwh,
        "electricity_kwh_per_agent": gwh * 1e6 / agents if agents else 0.0,
        "ev_share": n_ev / n_vehicles if n_vehicles else 0.0,
    }
    if ref:
        reduction = ref["co2_kt"] - co2_kt
        added = gwh - ref["electricity_gwh"]
        row["co2_reduction_kt"] = reduction
        row["co2_reduction_pct"] = reduction / ref["co2_kt"] * 100 if ref["co2_kt"] else 0.0
        row["added_electricity_gwh"] = added
        row["kappa_g_per_kwh"] = reduction * 1e9 / (added * 1e6) if added > 0 else None
        row["load_mw"] = {str(w): float(load_mw(added, w)) for w in CHARGING_WINDOWS_H}
    return row
