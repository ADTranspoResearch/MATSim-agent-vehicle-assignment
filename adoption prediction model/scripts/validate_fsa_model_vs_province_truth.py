from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


PROJECT_DIR = Path("/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model")
CACHE_DIR = PROJECT_DIR / ".cache"
DATASET_DIR = PROJECT_DIR / "datasets"
OUTPUT_DIR = PROJECT_DIR / "validation_outputs" / "fsa_model_validation_2025"
EXTERNAL_FILE = DATASET_DIR / "Fig1-NMVRegist.xlsx"

vehicle_cols = ["electric", "hev_sedan", "hev_suv", "ice_sedan", "ice_suv", "ice_van/pickup"]
quarter_order = ["T1", "T2", "T3", "T4"]
SHARE_DELTA_CLIP = (-0.05, 0.05)
MAX_ELECTRIC_ENTRY_SHARE = 0.45
DAMPING_END_FACTOR = 0.35
HYBRID_LINEAR_BLEND = {
    "electric": 1.0,
    "hev_sedan": 0.0,
    "hev_suv": 1.0,
    "ice_sedan": 0.0,
    "ice_suv": 0.0,
    "ice_van/pickup": 0.0,
}
SHRINKAGE_K = 500.0


def build_external_annual_benchmark(path: Path) -> pd.DataFrame:
    raw_external = pd.read_excel(path, sheet_name="Sheet 1", header=None)
    years = raw_external.iloc[0, 2:].ffill().astype(int).tolist()
    quarters = raw_external.iloc[1, 2:].tolist()
    records = []
    current_body_class = None
    for row_idx in range(2, len(raw_external)):
        row = raw_external.iloc[row_idx]
        if pd.notna(row[0]):
            current_body_class = str(row[0]).strip()
        fuel_type = row[1]
        if pd.isna(fuel_type):
            continue
        fuel_type = str(fuel_type).strip()
        for year, quarter, value in zip(years, quarters, row.iloc[2:].tolist()):
            if pd.isna(value):
                continue
            records.append(
                {
                    "body_class": current_body_class,
                    "fuel_type": fuel_type,
                    "year": int(year),
                    "quarter": str(quarter),
                    "registrations": float(value),
                }
            )
    external_long = pd.DataFrame(records)
    quarterly_cube = (
        external_long.pivot_table(
            index=["year", "quarter"],
            columns=["body_class", "fuel_type"],
            values="registrations",
            aggfunc="sum",
            fill_value=0,
        )
        .sort_index()
    )
    quarterly_cube.columns = pd.MultiIndex.from_tuples(quarterly_cube.columns)

    def qcol(body_class, fuel_type):
        if (body_class, fuel_type) in quarterly_cube.columns:
            return quarterly_cube[(body_class, fuel_type)]
        return pd.Series(0.0, index=quarterly_cube.index)

    counts = pd.DataFrame(index=quarterly_cube.index)
    counts["electric"] = qcol("Total, vehicle type", "Battery electric")
    counts["hev_sedan"] = qcol("Passenger cars", "Plug-in hybrid electric") + qcol("Passenger cars", "Hybrid electric")
    counts["hev_suv"] = qcol("Multi-purpose vehicles", "Plug-in hybrid electric") + qcol(
        "Multi-purpose vehicles", "Hybrid electric"
    )
    counts["ice_sedan"] = qcol("Passenger cars", "Gasoline") + qcol("Passenger cars", "Diesel") + qcol(
        "Passenger cars", "Other fuel types"
    )
    counts["ice_suv"] = qcol("Multi-purpose vehicles", "Gasoline") + qcol("Multi-purpose vehicles", "Diesel") + qcol(
        "Multi-purpose vehicles", "Other fuel types"
    )
    counts["total_registrations"] = quarterly_cube.xs("Total, vehicle type", axis=1, level=0).sum(axis=1)
    counts["ice_van/pickup"] = (
        counts["total_registrations"] - counts[["electric", "hev_sedan", "hev_suv", "ice_sedan", "ice_suv"]].sum(axis=1)
    ).clip(lower=0)
    counts = counts.reset_index()
    counts["quarter_num"] = counts["quarter"].map({q: i + 1 for i, q in enumerate(quarter_order)})
    trailing = counts.sort_values(["year", "quarter_num"]).reset_index(drop=True)
    for col in vehicle_cols + ["total_registrations"]:
        trailing[f"{col}_trailing4"] = trailing[col].rolling(4, min_periods=4).sum()
    annual_counts = counts.groupby("year")[vehicle_cols + ["total_registrations"]].sum()
    annual = annual_counts[vehicle_cols].div(annual_counts["total_registrations"], axis=0)
    row_2025 = trailing.loc[(trailing["year"] == 2025) & (trailing["quarter"] == "T1")].iloc[0]
    for col in vehicle_cols:
        annual.loc[2025, col] = row_2025[f"{col}_trailing4"] / row_2025["total_registrations_trailing4"]
    return annual.sort_index()


def normalize(share: pd.Series) -> pd.Series:
    share = share.clip(lower=0)
    share = share / share.sum() if share.sum() > 0 else share.copy()
    share["electric"] = min(float(share["electric"]), MAX_ELECTRIC_ENTRY_SHARE)
    non_electric = share.drop("electric")
    if non_electric.sum() > 0:
        share.loc[non_electric.index] = non_electric * ((1 - share["electric"]) / non_electric.sum())
    return share


def forecast_hybrid_delta(history: pd.DataFrame, future_years: list[int]) -> pd.DataFrame:
    delta = history[vehicle_cols].diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*SHARE_DELTA_CLIP)
    avg_delta = delta.mean().reindex(vehicle_cols).fillna(0)
    current = history.loc[int(history.index.max()), vehicle_cols].astype(float).copy()
    preds = {}
    horizon = max(1, len(future_years))
    for step, year in enumerate(future_years, start=1):
        damping = 1 - (1 - DAMPING_END_FACTOR) * (step / horizon)
        next_share = current.copy()
        for col in vehicle_cols:
            linear_weight = HYBRID_LINEAR_BLEND[col]
            avg_component = avg_delta[col] * damping
            series = delta[col].dropna()
            if len(series) >= 2:
                x = series.index.to_numpy(dtype=float)
                y = series.to_numpy(dtype=float)
                slope, intercept = np.polyfit(x, y, 1)
                linear_component = float(np.clip(intercept + slope * year, *SHARE_DELTA_CLIP))
            elif len(series) == 1:
                linear_component = float(series.iloc[-1])
            else:
                linear_component = 0.0
            next_share[col] = current[col] + (1 - linear_weight) * avg_component + linear_weight * linear_component
        current = normalize(next_share)
        preds[year] = current.copy()
    return pd.DataFrame(preds).T


def main():
    sns.set_theme(style="whitegrid")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    observed = build_external_annual_benchmark(EXTERNAL_FILE)
    future_years = list(range(2021, 2026))
    province_forecast = forecast_hybrid_delta(observed.loc[2017:2020], future_years)

    entry_counts = pd.read_pickle(CACHE_DIR / "saq_entry_counts.pkl")
    train_years = list(range(2017, 2021))
    fsa_entry = (
        entry_counts.pivot_table(index=["fsa", "AnneeSAAQ"], columns="vehicle_type", values="Entrant", aggfunc="sum", fill_value=0)
        .reindex(columns=vehicle_cols, fill_value=0)
        .sort_index()
    )
    fsa_entry["total_entries"] = fsa_entry.sum(axis=1)
    province_entries_by_year = fsa_entry["total_entries"].groupby(level="AnneeSAAQ").sum()
    province_avg_entries_train = float(province_entries_by_year.loc[train_years].mean())
    forecast_rows = []
    for fsa in sorted(fsa_entry.index.get_level_values("fsa").unique()):
        hist = fsa_entry.xs(fsa, level="fsa").copy()
        hist = hist.reindex(train_years, fill_value=0)
        hist["total_entries"] = hist[vehicle_cols].sum(axis=1)
        local_share_hist = hist[vehicle_cols].div(hist["total_entries"].replace(0, np.nan), axis=0).fillna(0)
        local_delta = local_share_hist.diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*SHARE_DELTA_CLIP)
        avg_local_delta = local_delta.mean().reindex(vehicle_cols).fillna(0)
        avg_entries = float(hist["total_entries"].mean())
        weight = avg_entries / (avg_entries + SHRINKAGE_K) if avg_entries >= 0 else 0.0
        current_local = local_share_hist.loc[2020, vehicle_cols].astype(float).copy()
        if current_local.sum() == 0:
            current_local = province_forecast.loc[2021, vehicle_cols].astype(float).copy()
        current_local = current_local / current_local.sum()

        stable_entry_weight = avg_entries / province_avg_entries_train if province_avg_entries_train > 0 else 0.0

        for year in future_years:
            next_local = normalize(current_local + avg_local_delta)
            province_row = province_forecast.loc[year, vehicle_cols].astype(float)
            blended = normalize(weight * next_local + (1 - weight) * province_row)
            forecast_rows.append(
                {
                    "fsa": fsa,
                    "year": year,
                    "entry_weight": stable_entry_weight,
                    **{col: float(blended[col]) for col in vehicle_cols},
                }
            )
            current_local = next_local.copy()

    fsa_pred = pd.DataFrame(forecast_rows)
    # Normalize FSA entry weights by year so aggregated shares are interpretable.
    fsa_pred["entry_weight"] = fsa_pred.groupby("year")["entry_weight"].transform(lambda s: s / s.sum() if s.sum() > 0 else 0)

    agg_rows = []
    for year, group in fsa_pred.groupby("year"):
        row = {"year": year}
        for col in vehicle_cols:
            row[col] = float((group[col] * group["entry_weight"]).sum())
        agg_rows.append(row)
    aggregate_pred = pd.DataFrame(agg_rows).set_index("year").sort_index()
    observed_actual = observed.loc[future_years, vehicle_cols]

    long_rows = []
    for year in future_years:
        for col in vehicle_cols:
            pred = float(aggregate_pred.loc[year, col])
            obs = float(observed_actual.loc[year, col])
            long_rows.append(
                {
                    "year": year,
                    "vehicle_type": col,
                    "predicted_share": pred,
                    "observed_share": obs,
                    "error": pred - obs,
                    "abs_error": abs(pred - obs),
                    "squared_error": (pred - obs) ** 2,
                }
            )
    long_df = pd.DataFrame(long_rows)
    overall = pd.DataFrame(
        [
            {
                "mae": long_df["abs_error"].mean(),
                "rmse": float(np.sqrt(long_df["squared_error"].mean())),
                "mean_error": long_df["error"].mean(),
                "max_abs_error": long_df["abs_error"].max(),
            }
        ]
    )
    by_type = (
        long_df.groupby("vehicle_type")
        .agg(
            mae=("abs_error", "mean"),
            rmse=("squared_error", lambda x: float(np.sqrt(np.mean(x)))),
            mean_error=("error", "mean"),
            max_abs_error=("abs_error", "max"),
        )
        .reset_index()
    )

    long_df.to_csv(OUTPUT_DIR / "fsa_aggregate_vs_province_long.csv", index=False)
    overall.to_csv(OUTPUT_DIR / "fsa_aggregate_validation_overall.csv", index=False)
    by_type.to_csv(OUTPUT_DIR / "fsa_aggregate_validation_by_type.csv", index=False)
    aggregate_pred.to_csv(OUTPUT_DIR / "fsa_aggregate_predicted_sales_share.csv")

    fig, axes = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
    axes = axes.flatten()
    for ax, col in zip(axes, vehicle_cols):
        ax.plot(observed_actual.index, observed_actual[col], marker="o", linewidth=2, label="Observed province")
        ax.plot(aggregate_pred.index, aggregate_pred[col], marker="s", linestyle="--", label="Aggregated FSA prediction")
        ax.set_title(col)
        ax.set_ylabel("Sales share")
        ax.legend()
    plt.suptitle("Aggregated FSA Forecast vs Observed Quebec Sales Share (2021-2025)", y=1.02)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "fsa_aggregate_vs_province_by_type.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    print("FSA aggregate validation overall")
    print(overall.to_string(index=False))
    print("\nOutputs written to:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
