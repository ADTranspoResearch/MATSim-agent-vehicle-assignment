"""
Backtest of the manuscript's baseline (BAU) new-vehicle share model against
observed 2021-2025 Quebec registrations.

Implements, at the province level, exactly the specification in Section 3.2.3
of the TR Part D manuscript ("Where EV adoption and transport emissions
diverge"):

  1. Mean historical relative growth rate per vehicle type from total stock
     counts over 2013-2020 (Eq. historical_growth).
  2. New-vehicle shares initialized at the observed 2020 entrant composition
     and advanced by normalized multiplicative reweighting, with the EV weight
     damped by (1 - s_EV,t-1) (Eqs. weights, reweight).
  3. The EV trajectory refitted with a bounded Gompertz curve anchored at the
     observed 2020 EV entrant share and at the reweighted trajectory's plateau
     year (first year >= 2030 with annual increment <= 0.005, else the year of
     maximum share) (Eq. gompertz).
  4. Non-EV shares proportionally rescaled so shares sum to one.

Truth data: observed province-wide new-vehicle sales shares 2021-2025 built
from the Statistics Canada new-motor-vehicle registrations benchmark
(validation_outputs/model_validation_2025/observed_sales_share_2017_2025.csv).

Outputs (validation_outputs/manuscript_bau_backtest/):
  predicted_vs_observed_2021_2025.csv
  backtest_error_summary.csv
  manuscript_bau_backtest.png
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_DIR / ".cache"
TRUTH_FILE = (
    PROJECT_DIR
    / "validation_outputs"
    / "model_validation_2025"
    / "observed_sales_share_2017_2025.csv"
)
OUTPUT_DIR = PROJECT_DIR / "validation_outputs" / "manuscript_bau_backtest"

VEHICLE_COLS = ["electric", "hev_sedan", "hev_suv", "ice_sedan", "ice_suv", "ice_van/pickup"]
TRAIN_YEARS = list(range(2013, 2021))
FORECAST_YEARS = list(range(2021, 2026))
PLATEAU_INCREMENT = 0.005
PLATEAU_SEARCH_START = 2030
PROJECTION_END = 2040
BASE_YEAR = 2020


def load_province_counts() -> tuple[pd.DataFrame, pd.Series]:
    """Province-level stock counts per type/year and 2020 entrant shares."""
    stock = pd.read_pickle(CACHE_DIR / "saq_vehicle_counts.pkl")
    stock_prov = (
        stock.groupby(["AnneeSAAQ", "vehicle_type"])["count"].sum().unstack()
    ).reindex(index=TRAIN_YEARS, columns=VEHICLE_COLS)

    entries = pd.read_pickle(CACHE_DIR / "saq_entry_counts.pkl")
    entr_2020 = (
        entries.loc[entries["AnneeSAAQ"] == BASE_YEAR]
        .groupby("vehicle_type")["Entrant"]
        .sum()
        .reindex(VEHICLE_COLS)
    )
    entrant_share_2020 = entr_2020 / entr_2020.sum()
    return stock_prov, entrant_share_2020


def mean_relative_growth(stock: pd.DataFrame) -> pd.Series:
    """Eq. historical_growth: mean year-over-year relative growth of stocks."""
    rel = stock.pct_change().iloc[1:]
    return rel.mean()


def reweighted_trajectory(s0: pd.Series, g_bar: pd.Series, years: list[int]) -> pd.DataFrame:
    """Eqs. weights + reweight, starting from the 2020 entrant composition."""
    shares = {BASE_YEAR: s0.copy()}
    current = s0.copy()
    for year in years:
        w = 1.0 + g_bar.copy()
        w["electric"] = 1.0 + g_bar["electric"] * (1.0 - current["electric"])
        nxt = w * current
        nxt = nxt / nxt.sum()
        shares[year] = nxt
        current = nxt
    return pd.DataFrame(shares).T


def gompertz_refit(traj: pd.DataFrame) -> pd.Series:
    """Eq. gompertz: solve a, k from the 2020 anchor and the plateau anchor."""
    s0 = float(traj.loc[BASE_YEAR, "electric"])
    ev = traj["electric"]
    increments = ev.diff()
    plateau_year = None
    for year in ev.index:
        if year >= PLATEAU_SEARCH_START and increments.loc[year] <= PLATEAU_INCREMENT:
            plateau_year = int(year)
            break
    if plateau_year is None:
        plateau_year = int(ev.idxmax())
    s_p = float(ev.loc[plateau_year])

    a = -np.log(s0)
    ratio = np.log(s_p) / np.log(s0)  # e^{-k (tp - tb)}
    k = -np.log(ratio) / (plateau_year - BASE_YEAR)

    years = np.arange(BASE_YEAR, PROJECTION_END + 1)
    fitted = np.exp(-a * np.exp(-k * (years - BASE_YEAR)))
    out = pd.Series(fitted, index=years, name="electric_gompertz")
    out.attrs["a"] = a
    out.attrs["k"] = k
    out.attrs["plateau_year"] = plateau_year
    out.attrs["plateau_share"] = s_p
    return out


def rescale_non_ev(traj: pd.DataFrame, ev_fit: pd.Series) -> pd.DataFrame:
    """Replace the EV column with the Gompertz fit; rescale non-EV shares."""
    out = traj.copy()
    for year in out.index:
        ev_new = float(ev_fit.loc[year])
        ev_old = float(out.loc[year, "electric"])
        scale = (1.0 - ev_new) / (1.0 - ev_old)
        for col in VEHICLE_COLS:
            if col != "electric":
                out.loc[year, col] *= scale
        out.loc[year, "electric"] = ev_new
    return out


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stock, s2020 = load_province_counts()
    g_bar = mean_relative_growth(stock)
    traj = reweighted_trajectory(s2020, g_bar, list(range(2021, PROJECTION_END + 1)))
    ev_fit = gompertz_refit(traj)
    predicted = rescale_non_ev(traj, ev_fit)

    observed = pd.read_csv(TRUTH_FILE, index_col="year").reindex(columns=VEHICLE_COLS)
    obs = observed.loc[FORECAST_YEARS]
    pred = predicted.loc[FORECAST_YEARS, VEHICLE_COLS]

    err = pred - obs
    long_rows = []
    for year in FORECAST_YEARS:
        for col in VEHICLE_COLS:
            long_rows.append(
                {
                    "year": year,
                    "vehicle_type": col,
                    "predicted": pred.loc[year, col],
                    "observed": obs.loc[year, col],
                    "error": err.loc[year, col],
                }
            )
    long_df = pd.DataFrame(long_rows)
    long_df.to_csv(OUTPUT_DIR / "predicted_vs_observed_2021_2025.csv", index=False)

    summary = pd.DataFrame(
        {
            "mae": err.abs().mean(),
            "rmse": np.sqrt((err**2).mean()),
            "mean_error": err.mean(),
            "max_abs_error": err.abs().max(),
        }
    )
    overall = pd.DataFrame(
        {
            "mae": [err.abs().values.mean()],
            "rmse": [np.sqrt((err.values**2).mean())],
            "mean_error": [err.values.mean()],
            "max_abs_error": [np.abs(err.values).max()],
        },
        index=["overall"],
    )
    ev_row = summary.loc[["electric"]]
    pd.concat([overall, summary]).to_csv(OUTPUT_DIR / "backtest_error_summary.csv")

    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    years_plot = list(range(2017, 2026))
    ax.plot(
        observed.loc[years_plot].index,
        100 * observed.loc[years_plot, "electric"],
        "o-",
        color="black",
        label="Observed EV sales share",
    )
    fit_years = [y for y in ev_fit.index if y <= 2030]
    ax.plot(
        fit_years,
        100 * ev_fit.loc[fit_years],
        "s--",
        color="#3A6B8A",
        label="Manuscript BAU model (trained to 2020)",
    )
    ax.axvline(2020.5, color="0.6", lw=0.8, ls=":")
    ax.text(2020.6, ax.get_ylim()[1] * 0.95, "forecast", fontsize=8, color="0.4")
    ax.set_xlabel("Year")
    ax.set_ylabel("EV share of new-vehicle registrations (%)")
    ax.grid(alpha=0.3, lw=0.5)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "manuscript_bau_backtest.png", dpi=300)

    print("Gompertz parameters: a=%.4f k=%.4f plateau_year=%d plateau_share=%.4f"
          % (ev_fit.attrs["a"], ev_fit.attrs["k"], ev_fit.attrs["plateau_year"], ev_fit.attrs["plateau_share"]))
    print("\nEV share, predicted vs observed (%):")
    for year in FORECAST_YEARS:
        print(f"  {year}: pred={100*pred.loc[year,'electric']:.2f}  obs={100*obs.loc[year,'electric']:.2f}")
    print("\nOverall MAE=%.4f  EV MAE=%.4f  EV mean error=%.4f"
          % (overall.loc['overall','mae'], ev_row.loc['electric','mae'], ev_row.loc['electric','mean_error']))
    print("wrote", OUTPUT_DIR)


if __name__ == "__main__":
    main()
