from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, OUTPUT_DIR, VEHICLE_TYPES
from .data import build_external_annual_benchmark, load_entry_counts, load_entry_full, load_population_q1_series, load_vehicle_counts


def normalize_share(share: pd.Series, config=DEFAULT_CONFIG) -> pd.Series:
    share = share.clip(lower=0)
    share = share / share.sum() if share.sum() > 0 else share.copy()
    share["electric"] = min(float(share["electric"]), config.max_electric_entry_share)
    non_electric = share.drop("electric")
    if non_electric.sum() > 0:
        share.loc[non_electric.index] = non_electric * ((1 - share["electric"]) / non_electric.sum())
    return share


def compute_share_delta(history: pd.DataFrame, config=DEFAULT_CONFIG) -> pd.DataFrame:
    return history[VEHICLE_TYPES].diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*config.share_delta_clip)


def weighted_average_delta(delta: pd.DataFrame, config=DEFAULT_CONFIG) -> tuple[pd.Series, pd.DataFrame]:
    years = delta.index.to_list()
    raw_weights = pd.Series(
        [1 + config.weighted_delta_growth * (year - years[0]) for year in years],
        index=years,
        dtype=float,
    ).clip(lower=0.1)
    weights = raw_weights / raw_weights.sum()
    weighted_delta = delta.mul(weights, axis=0).sum(axis=0).reindex(VEHICLE_TYPES).fillna(0)
    weight_table = pd.DataFrame({"year": years, "weight": weights.values})
    return weighted_delta, weight_table


def fit_turnover_projection(series: pd.Series, future_years: list[int], config=DEFAULT_CONFIG) -> pd.Series:
    hist = series.dropna().copy()
    if len(hist) < 2:
        default_value = float(hist.iloc[-1]) if len(hist) else 0.0
        return pd.Series(default_value, index=future_years, dtype=float).clip(*config.turnover_rate_clip)

    x = hist.index.to_numpy(dtype=float)
    y = hist.to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = pd.Series({year: intercept + slope * year for year in future_years}, dtype=float)
    return pred.clip(*config.turnover_rate_clip)


def build_province_history(vehicle_counts: pd.DataFrame, entry_counts: pd.DataFrame, entry_full: pd.DataFrame, config=DEFAULT_CONFIG):
    fleet_hist = (
        vehicle_counts.pivot_table(index="AnneeSAAQ", columns="vehicle_type", values="count", aggfunc="sum", fill_value=0)
        .reindex(columns=VEHICLE_TYPES, fill_value=0)
        .sort_index()
    )
    fleet_hist["total_vehicles"] = fleet_hist[VEHICLE_TYPES].sum(axis=1)

    entry_hist = (
        entry_counts.pivot_table(
            index="AnneeSAAQ",
            columns="vehicle_type",
            values=config.entry_flag,
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=VEHICLE_TYPES, fill_value=0)
        .sort_index()
    )
    entry_hist["total_entries"] = entry_hist[VEHICLE_TYPES].sum(axis=1)

    exit_hist = (
        entry_full.pivot_table(
            index="AnneeSAAQ",
            columns="vehicle_type",
            values=config.exit_flag,
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=VEHICLE_TYPES, fill_value=0)
        .sort_index()
    )
    exit_hist["total_exits"] = exit_hist[VEHICLE_TYPES].sum(axis=1)

    return fleet_hist, entry_hist, exit_hist


def build_population_linked_stock_controls(
    fleet_hist: pd.DataFrame,
    entry_hist: pd.DataFrame,
    exit_hist: pd.DataFrame,
    population_q1: pd.Series,
    config=DEFAULT_CONFIG,
):
    flow_rates = pd.DataFrame(index=fleet_hist.index)
    flow_rates["fleet_prev_year"] = fleet_hist["total_vehicles"].shift(1)
    flow_rates["entry_rate"] = (entry_hist["total_entries"] / flow_rates["fleet_prev_year"]).replace([np.inf, -np.inf], np.nan)
    flow_rates["exit_rate"] = (exit_hist["total_exits"] / flow_rates["fleet_prev_year"]).replace([np.inf, -np.inf], np.nan)
    flow_source = flow_rates.dropna().copy()

    last_observed_year = int(fleet_hist.index.max())
    future_years = list(range(last_observed_year + 1, config.forecast_end_year + 1))

    population_growth = population_q1.pct_change()
    start_year, end_year = config.population_growth_window
    reference_population_growth = float(population_growth.loc[start_year:end_year].mean())

    future_population_growth = pd.Series(index=future_years, dtype=float)
    for year in future_years:
        if year in population_growth.index and pd.notna(population_growth.loc[year]):
            future_population_growth.loc[year] = float(population_growth.loc[year])
        else:
            future_population_growth.loc[year] = reference_population_growth

    if config.turnover_model == "linear":
        future_turnover_rate = fit_turnover_projection(flow_source["entry_rate"], future_years, config)
    else:
        future_turnover_rate = pd.Series(flow_source["entry_rate"].mean(), index=future_years, dtype=float).clip(
            *config.turnover_rate_clip
        )

    target_total_fleet = pd.Series(index=[last_observed_year] + future_years, dtype=float)
    target_total_fleet.loc[last_observed_year] = float(fleet_hist.loc[last_observed_year, "total_vehicles"])
    for year in future_years:
        target_total_fleet.loc[year] = target_total_fleet.loc[year - 1] * (1 + float(future_population_growth.loc[year]))

    population_reference_summary = pd.DataFrame(
        {"population_q1": population_q1, "population_growth": population_growth}
    ).sort_index()
    future_stock_controls = pd.DataFrame(
        {
            "future_turnover_rate": future_turnover_rate,
            "future_population_growth": future_population_growth,
            "target_total_fleet": target_total_fleet.loc[future_years],
        }
    )
    return future_turnover_rate, future_population_growth, target_total_fleet, population_reference_summary, future_stock_controls


def build_entry_share_forecast(entry_hist: pd.DataFrame, external_benchmark: pd.DataFrame, config=DEFAULT_CONFIG):
    last_observed_year = int(entry_hist.index.max())
    future_years = list(range(last_observed_year + 1, config.forecast_end_year + 1))

    calibration_source = external_benchmark.loc[config.weighted_delta_start_year : config.observed_share_end_year].copy()
    benchmark_delta = compute_share_delta(calibration_source, config)
    avg_benchmark_delta, weighted_delta_summary = weighted_average_delta(benchmark_delta, config)

    entry_share_hist = entry_hist[VEHICLE_TYPES].div(entry_hist["total_entries"].replace(0, np.nan), axis=0).fillna(0)
    entry_share_future = entry_share_hist.copy()

    for year in range(last_observed_year + 1, min(config.observed_share_end_year, config.forecast_end_year) + 1):
        entry_share_future.loc[year, VEHICLE_TYPES] = external_benchmark.loc[year, VEHICLE_TYPES].astype(float)

    current_share = external_benchmark.loc[config.observed_share_end_year, VEHICLE_TYPES].astype(float).copy()
    future_span = max(1, config.forecast_end_year - config.observed_share_end_year)
    for position, year in enumerate(range(config.observed_share_end_year + 1, config.forecast_end_year + 1), start=1):
        damping = 1 - (1 - config.damping_end_factor) * (position / future_span)
        current_share = normalize_share(current_share + avg_benchmark_delta * damping, config)
        entry_share_future.loc[year, VEHICLE_TYPES] = current_share

    sales_share_by_year = pd.concat(
        [
            entry_share_hist.loc[entry_share_hist.index <= last_observed_year, VEHICLE_TYPES],
            entry_share_future.loc[future_years, VEHICLE_TYPES],
        ]
    )
    sales_share_by_year = sales_share_by_year[~sales_share_by_year.index.duplicated(keep="last")].sort_index()
    sales_share_by_year.index.name = "year"
    sales_share_by_year["source"] = np.where(
        sales_share_by_year.index <= last_observed_year,
        "observed_saaq",
        np.where(sales_share_by_year.index <= config.observed_share_end_year, "observed_external", "forecast"),
    )
    return entry_share_future, sales_share_by_year, weighted_delta_summary


def build_exit_share_forecast(exit_hist: pd.DataFrame, config=DEFAULT_CONFIG):
    last_observed_year = int(exit_hist.index.max())
    future_years = list(range(last_observed_year + 1, config.forecast_end_year + 1))

    exit_share_hist = exit_hist[VEHICLE_TYPES].div(exit_hist["total_exits"].replace(0, np.nan), axis=0).fillna(0)
    avg_exit_delta = compute_share_delta(exit_share_hist, config).mean().reindex(VEHICLE_TYPES).fillna(0)

    exit_share_future = exit_share_hist.copy()
    current_share = exit_share_hist.loc[last_observed_year, VEHICLE_TYPES].astype(float).copy()
    current_share = current_share / current_share.sum() if current_share.sum() > 0 else pd.Series(
        1 / len(VEHICLE_TYPES), index=VEHICLE_TYPES
    )

    for year in future_years:
        current_share = current_share + avg_exit_delta
        current_share = current_share.clip(lower=0)
        current_share = current_share / current_share.sum() if current_share.sum() > 0 else current_share.copy()
        exit_share_future.loc[year, VEHICLE_TYPES] = current_share

    return exit_share_future


def rebuild_fleet(
    fleet_hist: pd.DataFrame,
    entry_share_future: pd.DataFrame,
    exit_share_future: pd.DataFrame,
    future_turnover_rate: pd.Series,
    future_population_growth: pd.Series,
    target_total_fleet: pd.Series,
    config=DEFAULT_CONFIG,
):
    projected_counts = fleet_hist.copy()
    current_counts = projected_counts.loc[int(fleet_hist.index.max()), VEHICLE_TYPES].astype(float).copy()
    projection_rows = []

    for year in range(int(fleet_hist.index.max()) + 1, config.forecast_end_year + 1):
        current_total = float(current_counts.sum())
        turnover_rate = float(future_turnover_rate.loc[year])
        target_total = float(target_total_fleet.loc[year])
        entries = current_total * turnover_rate
        exits = max(current_total + entries - target_total, 0.0)
        additions = entries * entry_share_future.loc[year, VEHICLE_TYPES].astype(float)
        removals = exits * exit_share_future.loc[year, VEHICLE_TYPES].astype(float)

        next_counts = (current_counts + additions - removals).clip(lower=0)
        next_total = float(next_counts.sum())
        if next_total > 0 and target_total > 0:
            next_counts = next_counts * (target_total / next_total)
            next_total = float(next_counts.sum())

        projected_counts.loc[year, VEHICLE_TYPES] = next_counts
        projected_counts.loc[year, "total_vehicles"] = next_total
        projection_rows.append(
            {
                "year": year,
                "turnover_rate": turnover_rate,
                "population_growth": float(future_population_growth.loc[year]),
                "entries": entries,
                "exits": exits,
                "target_total_vehicles": target_total,
                "total_vehicles": next_total,
            }
        )
        current_counts = next_counts.copy()

    projected_counts.index.name = "year"
    projected_market_share = projected_counts[VEHICLE_TYPES].div(projected_counts[VEHICLE_TYPES].sum(axis=1), axis=0).fillna(0)
    projected_market_share.index.name = "year"
    projection_summary = pd.DataFrame(projection_rows)
    return projected_counts, projected_market_share, projection_summary


def run_province_model(config=DEFAULT_CONFIG) -> dict[str, pd.DataFrame]:
    vehicle_counts = load_vehicle_counts()
    entry_counts = load_entry_counts()
    entry_full = load_entry_full()
    external_benchmark = build_external_annual_benchmark()
    population_q1 = load_population_q1_series()

    fleet_hist, entry_hist, exit_hist = build_province_history(vehicle_counts, entry_counts, entry_full, config)
    future_turnover_rate, future_population_growth, target_total_fleet, population_reference_summary, future_stock_controls = build_population_linked_stock_controls(
        fleet_hist, entry_hist, exit_hist, population_q1, config
    )
    entry_share_future, sales_share_by_year, weighted_delta_summary = build_entry_share_forecast(entry_hist, external_benchmark, config)
    exit_share_future = build_exit_share_forecast(exit_hist, config)
    projected_counts, projected_market_share, projection_summary = rebuild_fleet(
        fleet_hist,
        entry_share_future,
        exit_share_future,
        future_turnover_rate,
        future_population_growth,
        target_total_fleet,
        config,
    )

    fleet_share_by_year = projected_market_share.copy()
    fleet_share_by_year["source"] = np.where(fleet_share_by_year.index <= fleet_hist.index.max(), "observed_saaq", "forecast")
    vehicle_counts_by_year = projected_counts.copy()
    vehicle_counts_by_year["source"] = np.where(vehicle_counts_by_year.index <= fleet_hist.index.max(), "observed_saaq", "forecast")

    selected_year = min(config.selected_year, config.forecast_end_year)
    summary_year = pd.DataFrame(
        {
            f"count_{selected_year}": projected_counts.loc[selected_year, VEHICLE_TYPES],
            f"fleet_share_{selected_year}": projected_market_share.loc[selected_year, VEHICLE_TYPES],
            f"sales_share_{selected_year}": sales_share_by_year.loc[selected_year, VEHICLE_TYPES],
        }
    ).sort_values(f"count_{selected_year}", ascending=False)

    return {
        "external_benchmark": external_benchmark,
        "fleet_hist": fleet_hist,
        "entry_hist": entry_hist,
        "exit_hist": exit_hist,
        "sales_share_by_year": sales_share_by_year,
        "fleet_share_by_year": fleet_share_by_year,
        "vehicle_counts_by_year": vehicle_counts_by_year,
        "weighted_delta_summary": weighted_delta_summary,
        "population_reference_summary": population_reference_summary,
        "future_stock_controls": future_stock_controls,
        "projection_summary": projection_summary,
        "summary_year": summary_year,
        "target_total_fleet": target_total_fleet.to_frame(name="target_total_fleet"),
    }


def save_province_outputs(result: dict[str, pd.DataFrame], output_dir: Optional[Path] = None) -> Path:
    output_dir = output_dir or (OUTPUT_DIR / "province")
    output_dir.mkdir(parents=True, exist_ok=True)
    result["sales_share_by_year"].to_csv(output_dir / "sales_share_by_year.csv")
    result["fleet_share_by_year"].to_csv(output_dir / "fleet_share_by_year.csv")
    result["vehicle_counts_by_year"].to_csv(output_dir / "vehicle_counts_by_year.csv")
    result["weighted_delta_summary"].to_csv(output_dir / "weighted_delta_summary.csv", index=False)
    result["population_reference_summary"].to_csv(output_dir / "population_reference_summary.csv")
    result["future_stock_controls"].to_csv(output_dir / "future_stock_controls.csv")
    result["projection_summary"].to_csv(output_dir / "projection_summary.csv", index=False)
    result["summary_year"].to_csv(output_dir / "summary_year.csv")
    result["target_total_fleet"].to_csv(output_dir / "target_total_fleet.csv")
    return output_dir
