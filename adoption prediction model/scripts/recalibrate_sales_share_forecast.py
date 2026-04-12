from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


PROJECT_DIR = Path("/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model")
DATASET_DIR = PROJECT_DIR / "datasets"
OUTPUT_DIR = PROJECT_DIR / "validation_outputs" / "recalibrated_sales_share_forecast"
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


def forecast_share_delta(history: pd.DataFrame, future_years: list[int]) -> pd.DataFrame:
    delta = history[vehicle_cols].diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*SHARE_DELTA_CLIP)
    avg_delta = delta.mean().reindex(vehicle_cols).fillna(0)
    current = history.loc[int(history.index.max()), vehicle_cols].astype(float).copy()
    preds = {}
    horizon = max(1, len(future_years))
    for step, year in enumerate(future_years, start=1):
        damping = 1 - (1 - DAMPING_END_FACTOR) * (step / horizon)
        current = normalize(current + avg_delta * damping)
        preds[year] = current.copy()
    return pd.DataFrame(preds).T


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
    observed.to_csv(OUTPUT_DIR / "observed_sales_share_2017_2025.csv")

    future_years = list(range(2026, 2036))
    baseline = forecast_share_delta(observed.loc[2021:2025], future_years)
    recalibrated = forecast_hybrid_delta(observed.loc[2021:2025], future_years)

    comparison = pd.concat({"baseline_share_delta": baseline, "recalibrated_hybrid_delta": recalibrated}, axis=1)
    comparison.to_csv(OUTPUT_DIR / "sales_share_forecast_comparison_2026_2035.csv")
    recalibrated.to_csv(OUTPUT_DIR / "recalibrated_sales_share_2026_2035.csv")

    summary_2035 = pd.DataFrame(
        {
            "baseline_2035": baseline.loc[2035],
            "recalibrated_2035": recalibrated.loc[2035],
            "difference": recalibrated.loc[2035] - baseline.loc[2035],
        }
    )
    summary_2035.to_csv(OUTPUT_DIR / "recalibrated_2035_summary.csv")

    fig, axes = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
    axes = axes.flatten()
    for ax, col in zip(axes, vehicle_cols):
        ax.plot(observed.loc[2017:2025].index, observed.loc[2017:2025, col], marker="o", linewidth=2, label="Observed")
        ax.plot(baseline.index, baseline[col], marker="s", linestyle="--", label="Baseline share-delta")
        ax.plot(recalibrated.index, recalibrated[col], marker="^", linestyle=":", label="Recalibrated hybrid-delta")
        ax.set_title(col)
        ax.set_ylabel("Sales share")
        ax.legend()
    plt.suptitle("Observed 2017-2025 and Forecasted 2026-2035 Sales Shares", y=1.02)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "recalibrated_sales_share_forecast.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    plot_df = summary_2035.reset_index().rename(columns={"index": "vehicle_type"})
    plot_df = plot_df.melt(id_vars="vehicle_type", value_vars=["baseline_2035", "recalibrated_2035"], var_name="forecast", value_name="share")
    sns.barplot(data=plot_df, x="vehicle_type", y="share", hue="forecast", ax=ax)
    ax.set_title("2035 Sales Share: Baseline vs Recalibrated")
    ax.set_xlabel("Vehicle type")
    ax.set_ylabel("Sales share")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "recalibrated_2035_barplot.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    print("Recalibrated 2035 summary")
    print(summary_2035.to_string())
    print("\nOutputs written to:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
