"""Approximate first-stage projections with an anchored Gompertz curve.

This is a second-stage fit to simulated shares, not a fit to historical EV
observations. Its residuals measure approximation error, not forecast accuracy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import least_squares


INITIAL_K = (0.02, 0.05, 0.1, 0.2, 0.5, 1.0)


@dataclass(frozen=True)
class AnchoredGompertzFit:
    anchor_year: int
    anchor_share: float
    a: float
    k: float
    fit_years: tuple[int, ...]
    sum_squared_error: float
    successful_starts: int

    def predict(self, years: Iterable[float]) -> np.ndarray:
        x = np.asarray(list(years), dtype=float)
        if x.ndim != 1 or not np.isfinite(x).all():
            raise ValueError("Prediction years must be finite and one dimensional.")
        with np.errstate(over="ignore", under="ignore"):
            inner = np.exp(np.clip(np.log(self.a) - self.k * (x - self.anchor_year), -745, 700))
            return np.exp(-inner)

    def to_dict(self):
        return asdict(self)


def fit_projected_ev_gompertz(
    years: Iterable[int],
    projected_shares: Iterable[float],
    anchor_year: int,
    anchor_share: float,
) -> AnchoredGompertzFit:
    """Fit k to all supplied predictions, holding K=1 and the actual anchor.

    Every prediction receives equal weight on the share scale. The anchor
    fixes a=-log(anchor_share), so its value is preserved exactly. Fit years
    are supplied explicitly and are unrelated to later prediction requests.
    """
    x = np.asarray(list(years), dtype=float)
    y = np.asarray(list(projected_shares), dtype=float)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y) or len(x) < 2:
        raise ValueError("At least two matching projected years/shares are required.")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("All predictions must be finite; none may be silently dropped.")
    if not np.equal(x, np.floor(x)).all() or len(np.unique(x)) != len(x):
        raise ValueError("Fit years must be unique integers.")
    if not np.isfinite(anchor_year) or anchor_year != int(anchor_year) or np.any(x <= anchor_year):
        raise ValueError("Fit years must follow an integer anchor year.")
    if not np.isfinite(anchor_share) or not 0 < anchor_share < 1:
        raise ValueError("The observed anchor share must be strictly between zero and one.")
    if np.any(y < 0) or np.any(y > 1):
        raise ValueError("Projected shares must lie in [0, 1].")
    order = np.argsort(x)
    x, y = x[order], y[order]
    a = float(-np.log(anchor_share))
    t = x - anchor_year

    def residual(params):
        return np.exp(-a * np.exp(-np.exp(params[0]) * t)) - y

    candidates = []
    for initial_k in INITIAL_K:
        result = least_squares(
            residual, [np.log(initial_k)], bounds=([-20.0], [5.0]),
            ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=10000,
        )
        if result.success and np.isfinite(result.fun).all():
            candidates.append((float(result.fun @ result.fun), result))
    if not candidates:
        raise RuntimeError("No anchored Gompertz optimization converged.")
    sse, best = min(candidates, key=lambda candidate: candidate[0])
    if np.isclose(best.x[0], -20, atol=1e-6) or np.isclose(best.x[0], 5, atol=1e-6):
        raise RuntimeError("The increasing curve reached a numerical bound; inspect the projections.")
    return AnchoredGompertzFit(
        anchor_year=int(anchor_year), anchor_share=float(anchor_share), a=a,
        k=float(np.exp(best.x[0])), fit_years=tuple(int(year) for year in x),
        sum_squared_error=sse, successful_starts=len(candidates),
    )


def replace_ev_shares(baseline: pd.DataFrame, ev_shares: Iterable[float]) -> pd.DataFrame:
    """Fill 1-EV using the same year's original non-EV relative proportions."""
    target = np.asarray(list(ev_shares), dtype=float)
    if target.shape != (len(baseline.columns),) or not np.isfinite(target).all():
        raise ValueError("One finite EV share per prediction year is required.")
    if np.any(target < 0) or np.any(target > 1) or "electric" not in baseline.index:
        raise ValueError("EV shares must be in [0, 1] and the baseline must include electric.")
    non_ev = baseline.index.difference(["electric"])
    mass = baseline.loc[non_ev].sum(axis=0)
    if mass.le(0).any():
        raise ValueError("The baseline must contain positive non-EV mass in every year.")
    adjusted = baseline.copy()
    adjusted.loc[non_ev] = baseline.loc[non_ev].div(mass, axis=1).mul(1 - target, axis=1)
    adjusted.loc["electric"] = target
    return adjusted
