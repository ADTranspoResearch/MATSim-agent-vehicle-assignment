from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, OUTPUT_DIR, VEHICLE_TYPES
from .data import load_entry_counts, load_entry_full, load_vehicle_counts
from .province import build_exit_share_forecast, normalize_share, run_province_model


def build_fsa_history(vehicle_counts: pd.DataFrame, entry_counts: pd.DataFrame, entry_full: pd.DataFrame, config=DEFAULT_CONFIG):
    fleet_hist = (
        vehicle_counts.pivot_table(index=["fsa", "AnneeSAAQ"], columns="vehicle_type", values="count", aggfunc="sum", fill_value=0)
        .reindex(columns=VEHICLE_TYPES, fill_value=0)
        .sort_index()
    )
    fleet_hist["total_vehicles"] = fleet_hist[VEHICLE_TYPES].sum(axis=1)

    entry_hist = (
        entry_counts.pivot_table(
            index=["fsa", "AnneeSAAQ"],
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
            index=["fsa", "AnneeSAAQ"],
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


def run_single_fsa(
    fsa: str,
    fsa_fleet: pd.DataFrame,
    fsa_entry: pd.DataFrame,
    fsa_exit: pd.DataFrame,
    province_result: dict[str, pd.DataFrame],
    config=DEFAULT_CONFIG,
) -> dict:
    prov_fleet = province_result["fleet_hist"]
    province_entry_share_future = province_result["sales_share_by_year"][VEHICLE_TYPES]
    province_exit_share_future = build_exit_share_forecast(province_result["exit_hist"], config)
    province_target_total_fleet = province_result["target_total_fleet"]["target_total_fleet"]
    province_turnover_rate = province_result["future_stock_controls"]["future_turnover_rate"]

    last_observed_year = int(prov_fleet.index.max())
    future_years = list(range(last_observed_year + 1, config.forecast_end_year + 1))
    historical_years = list(range(int(prov_fleet.index.min()), last_observed_year + 1))

    fleet_hist = fsa_fleet.xs(fsa, level="fsa").copy().sort_index().reindex(historical_years, fill_value=0)
    entry_hist = fsa_entry.xs(fsa, level="fsa").copy().sort_index().reindex(historical_years, fill_value=0)
    exit_hist = fsa_exit.xs(fsa, level="fsa").copy().sort_index().reindex(historical_years, fill_value=0)

    fleet_hist["total_vehicles"] = fleet_hist[VEHICLE_TYPES].sum(axis=1)
    entry_hist["total_entries"] = entry_hist[VEHICLE_TYPES].sum(axis=1)
    exit_hist["total_exits"] = exit_hist[VEHICLE_TYPES].sum(axis=1)

    local_entry_share_hist = entry_hist[VEHICLE_TYPES].div(entry_hist["total_entries"].replace(0, np.nan), axis=0).fillna(0)
    local_exit_share_hist = exit_hist[VEHICLE_TYPES].div(exit_hist["total_exits"].replace(0, np.nan), axis=0).fillna(0)

    local_entry_delta = local_entry_share_hist.diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*config.share_delta_clip)
    local_exit_delta = local_exit_share_hist.diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*config.share_delta_clip)

    avg_entries_per_year = float(entry_hist["total_entries"].mean()) if len(entry_hist) else 0.0
    shrinkage_weight = avg_entries_per_year / (avg_entries_per_year + config.shrinkage_k) if avg_entries_per_year >= 0 else 0.0

    avg_local_entry_delta = local_entry_delta.mean().reindex(VEHICLE_TYPES).fillna(0)
    avg_local_exit_delta = local_exit_delta.mean().reindex(VEHICLE_TYPES).fillna(0)

    local_sales_future = local_entry_share_hist.copy()
    current_local_sales = local_entry_share_hist.loc[last_observed_year, VEHICLE_TYPES].astype(float).copy()
    if current_local_sales.sum() == 0:
        current_local_sales = province_entry_share_future.loc[last_observed_year, VEHICLE_TYPES].astype(float).copy()
    current_local_sales = current_local_sales / current_local_sales.sum()

    for year in future_years:
        next_local = normalize_share(current_local_sales + avg_local_entry_delta, config)
        local_sales_future.loc[year, VEHICLE_TYPES] = next_local
        current_local_sales = next_local.copy()

    sales_share_future = province_entry_share_future.loc[future_years, VEHICLE_TYPES].copy()
    for year in future_years:
        province_row = province_entry_share_future.loc[year, VEHICLE_TYPES].astype(float)
        local_row = local_sales_future.loc[year, VEHICLE_TYPES].astype(float)
        sales_share_future.loc[year, VEHICLE_TYPES] = normalize_share(
            shrinkage_weight * local_row + (1 - shrinkage_weight) * province_row,
            config,
        )

    local_exit_future = local_exit_share_hist.copy()
    current_local_exit = local_exit_share_hist.loc[last_observed_year, VEHICLE_TYPES].astype(float).copy()
    if current_local_exit.sum() == 0:
        current_local_exit = province_exit_share_future.loc[last_observed_year, VEHICLE_TYPES].astype(float).copy()
    current_local_exit = current_local_exit / current_local_exit.sum()

    for year in future_years:
        next_local_exit = (current_local_exit + avg_local_exit_delta).clip(lower=0)
        next_local_exit = next_local_exit / next_local_exit.sum() if next_local_exit.sum() > 0 else current_local_exit.copy()
        province_exit_row = province_exit_share_future.loc[year, VEHICLE_TYPES].astype(float)
        local_exit_future.loc[year, VEHICLE_TYPES] = normalize_share(
            shrinkage_weight * next_local_exit + (1 - shrinkage_weight) * province_exit_row,
            config,
        )
        current_local_exit = next_local_exit.copy()

    province_hist_total = prov_fleet["total_vehicles"]
    fsa_hist_total = fleet_hist["total_vehicles"]
    recent_share_years = historical_years[-min(config.fsa_share_window, len(historical_years)) :]
    stable_fsa_share = float((fsa_hist_total.loc[recent_share_years] / province_hist_total.loc[recent_share_years]).mean())

    fsa_target_total = pd.Series(index=[last_observed_year] + future_years, dtype=float)
    fsa_target_total.loc[last_observed_year] = float(fleet_hist.loc[last_observed_year, "total_vehicles"])
    for year in future_years:
        fsa_target_total.loc[year] = max(float(province_target_total_fleet.loc[year]) * stable_fsa_share, 0.0)

    local_flow = pd.DataFrame(index=fleet_hist.index)
    local_flow["fleet_prev_year"] = fleet_hist["total_vehicles"].shift(1)
    local_flow["entry_rate"] = (entry_hist["total_entries"] / local_flow["fleet_prev_year"]).replace([np.inf, -np.inf], np.nan)
    local_avg_entry_rate = float(local_flow["entry_rate"].dropna().mean()) if not local_flow["entry_rate"].dropna().empty else float(
        province_turnover_rate.mean()
    )

    fsa_turnover_rate = pd.Series(index=future_years, dtype=float)
    for year in future_years:
        fsa_turnover_rate.loc[year] = shrinkage_weight * local_avg_entry_rate + (1 - shrinkage_weight) * float(
            province_turnover_rate.loc[year]
        )
        fsa_turnover_rate.loc[year] = float(np.clip(fsa_turnover_rate.loc[year], *config.turnover_rate_clip))

    projected_counts = fleet_hist.copy()
    current_counts = projected_counts.loc[last_observed_year, VEHICLE_TYPES].astype(float).copy()
    projection_rows = []
    for year in future_years:
        current_total = float(current_counts.sum())
        turnover_rate = float(fsa_turnover_rate.loc[year])
        target_total = float(fsa_target_total.loc[year])
        entries = current_total * turnover_rate
        exits = max(current_total + entries - target_total, 0.0)
        additions = entries * sales_share_future.loc[year, VEHICLE_TYPES].astype(float)
        removals = exits * local_exit_future.loc[year, VEHICLE_TYPES].astype(float)

        next_counts = (current_counts + additions - removals).clip(lower=0)
        next_total = float(next_counts.sum())
        if next_total > 0 and target_total > 0:
            next_counts = next_counts * (target_total / next_total)
            next_total = float(next_counts.sum())

        projected_counts.loc[year, VEHICLE_TYPES] = next_counts
        projected_counts.loc[year, "total_vehicles"] = next_total
        projection_rows.append(
            {
                "fsa": fsa,
                "year": year,
                "shrinkage_weight": shrinkage_weight,
                "avg_entries_per_year": avg_entries_per_year,
                "stable_fsa_share": stable_fsa_share,
                "turnover_rate": turnover_rate,
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

    sales_share_by_year = pd.concat(
        [
            local_entry_share_hist.loc[local_entry_share_hist.index <= last_observed_year, VEHICLE_TYPES],
            sales_share_future.loc[future_years, VEHICLE_TYPES],
        ]
    )
    sales_share_by_year = sales_share_by_year[~sales_share_by_year.index.duplicated(keep="last")].sort_index()
    sales_share_by_year.index.name = "year"

    diagnostics = {
        "fsa": fsa,
        "avg_entries_per_year": avg_entries_per_year,
        "shrinkage_weight": shrinkage_weight,
        "stable_fsa_share": stable_fsa_share,
        "last_observed_total": float(fleet_hist.loc[last_observed_year, "total_vehicles"]),
        f"projected_{config.forecast_end_year}_total": float(projected_counts.loc[config.forecast_end_year, "total_vehicles"]),
    }

    return {
        "diagnostics": diagnostics,
        "sales_share_by_year": sales_share_by_year,
        "projected_counts": projected_counts,
        "projected_market_share": projected_market_share,
        "projection_summary": pd.DataFrame(projection_rows),
    }


def run_fsa_model(config=DEFAULT_CONFIG) -> dict[str, pd.DataFrame]:
    province_result = run_province_model(config)
    vehicle_counts = load_vehicle_counts()
    entry_counts = load_entry_counts()
    entry_full = load_entry_full()
    fsa_fleet, fsa_entry, fsa_exit = build_fsa_history(vehicle_counts, entry_counts, entry_full, config)

    summary_rows = []
    sales_rows = []
    market_rows = []
    count_rows = []
    projection_rows = []

    for fsa in sorted(fsa_fleet.index.get_level_values("fsa").unique()):
        result = run_single_fsa(fsa, fsa_fleet, fsa_entry, fsa_exit, province_result, config)
        summary_rows.append(result["diagnostics"])

        sales_df = result["sales_share_by_year"].reset_index()
        sales_df.insert(0, "fsa", fsa)
        sales_df["source"] = np.where(sales_df["year"] <= int(province_result["fleet_hist"].index.max()), "observed_saaq", "forecast")
        sales_rows.append(sales_df)

        market_df = result["projected_market_share"].reset_index()
        market_df.insert(0, "fsa", fsa)
        market_df["source"] = np.where(market_df["year"] <= int(province_result["fleet_hist"].index.max()), "observed_saaq", "forecast")
        market_rows.append(market_df)

        count_df = result["projected_counts"].reset_index()
        count_df.insert(0, "fsa", fsa)
        count_df["source"] = np.where(count_df["year"] <= int(province_result["fleet_hist"].index.max()), "observed_saaq", "forecast")
        count_rows.append(count_df)

        projection_rows.append(result["projection_summary"])

    fsa_summary = pd.DataFrame(summary_rows).sort_values("shrinkage_weight", ascending=False)
    fsa_sales_share_by_year = pd.concat(sales_rows, ignore_index=True)
    fsa_fleet_share_by_year = pd.concat(market_rows, ignore_index=True)
    fsa_vehicle_counts_by_year = pd.concat(count_rows, ignore_index=True)
    fsa_projection_summary = pd.concat(projection_rows, ignore_index=True)

    selected_year = min(config.selected_year, config.forecast_end_year)
    summary_year = (
        fsa_fleet_share_by_year.loc[fsa_fleet_share_by_year["year"] == selected_year, ["fsa"] + VEHICLE_TYPES]
        .rename(columns={col: f"fleet_share_{col}" for col in VEHICLE_TYPES})
        .merge(
            fsa_sales_share_by_year.loc[fsa_sales_share_by_year["year"] == selected_year, ["fsa"] + VEHICLE_TYPES].rename(
                columns={col: f"sales_share_{col}" for col in VEHICLE_TYPES}
            ),
            on="fsa",
            how="left",
        )
        .merge(
            fsa_vehicle_counts_by_year.loc[fsa_vehicle_counts_by_year["year"] == selected_year, ["fsa", "total_vehicles"]],
            on="fsa",
            how="left",
        )
        .rename(columns={"total_vehicles": f"total_vehicles_{selected_year}"})
    )

    return {
        "province_result": province_result,
        "fsa_summary": fsa_summary,
        "fsa_sales_share_by_year": fsa_sales_share_by_year,
        "fsa_fleet_share_by_year": fsa_fleet_share_by_year,
        "fsa_vehicle_counts_by_year": fsa_vehicle_counts_by_year,
        "fsa_projection_summary": fsa_projection_summary,
        "summary_year": summary_year,
    }


def save_fsa_outputs(result: dict[str, pd.DataFrame], output_dir: Optional[Path] = None) -> Path:
    output_dir = output_dir or (OUTPUT_DIR / "fsa")
    output_dir.mkdir(parents=True, exist_ok=True)
    result["fsa_summary"].to_csv(output_dir / "fsa_summary.csv", index=False)
    result["fsa_sales_share_by_year"].to_csv(output_dir / "fsa_sales_share_by_year.csv", index=False)
    result["fsa_fleet_share_by_year"].to_csv(output_dir / "fsa_fleet_share_by_year.csv", index=False)
    result["fsa_vehicle_counts_by_year"].to_csv(output_dir / "fsa_vehicle_counts_by_year.csv", index=False)
    result["fsa_projection_summary"].to_csv(output_dir / "fsa_projection_summary.csv", index=False)
    result["summary_year"].to_csv(output_dir / "summary_year.csv", index=False)
    return output_dir
