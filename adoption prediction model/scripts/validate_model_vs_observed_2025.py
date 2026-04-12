from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


PROJECT_DIR = Path("/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model")
DATASET_DIR = PROJECT_DIR / "datasets"
OUTPUT_DIR = PROJECT_DIR / "validation_outputs" / "model_validation_2025"
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
        values = row.iloc[2:].tolist()
        for year, quarter, value in zip(years, quarters, values):
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

    external_mapped_counts = pd.DataFrame(index=quarterly_cube.index)
    external_mapped_counts["electric"] = qcol("Total, vehicle type", "Battery electric")
    external_mapped_counts["hev_sedan"] = qcol("Passenger cars", "Plug-in hybrid electric") + qcol(
        "Passenger cars", "Hybrid electric"
    )
    external_mapped_counts["hev_suv"] = qcol("Multi-purpose vehicles", "Plug-in hybrid electric") + qcol(
        "Multi-purpose vehicles", "Hybrid electric"
    )
    external_mapped_counts["ice_sedan"] = (
        qcol("Passenger cars", "Gasoline")
        + qcol("Passenger cars", "Diesel")
        + qcol("Passenger cars", "Other fuel types")
    )
    external_mapped_counts["ice_suv"] = (
        qcol("Multi-purpose vehicles", "Gasoline")
        + qcol("Multi-purpose vehicles", "Diesel")
        + qcol("Multi-purpose vehicles", "Other fuel types")
    )
    external_mapped_counts["total_registrations"] = quarterly_cube.xs("Total, vehicle type", axis=1, level=0).sum(axis=1)
    external_mapped_counts["ice_van/pickup"] = (
        external_mapped_counts["total_registrations"]
        - external_mapped_counts[["electric", "hev_sedan", "hev_suv", "ice_sedan", "ice_suv"]].sum(axis=1)
    ).clip(lower=0)

    external_mapped_counts = external_mapped_counts.reset_index()
    external_mapped_counts["quarter_num"] = external_mapped_counts["quarter"].map({q: i + 1 for i, q in enumerate(quarter_order)})
    external_trailing = external_mapped_counts.sort_values(["year", "quarter_num"]).reset_index(drop=True)
    for col in vehicle_cols + ["total_registrations"]:
        external_trailing[f"{col}_trailing4"] = external_trailing[col].rolling(4, min_periods=4).sum()

    external_trailing_shares = external_trailing[["year", "quarter"]].copy()
    for col in vehicle_cols:
        external_trailing_shares[f"{col}_trailing4_share"] = (
            external_trailing[f"{col}_trailing4"] / external_trailing["total_registrations_trailing4"]
        )

    external_annual_counts = external_mapped_counts.groupby("year")[vehicle_cols + ["total_registrations"]].sum()
    external_annual_benchmark = external_annual_counts[vehicle_cols].div(
        external_annual_counts["total_registrations"], axis=0
    )

    latest_trailing_row = external_trailing_shares.loc[
        (external_trailing_shares["year"] == 2025) & (external_trailing_shares["quarter"] == "T1")
    ].iloc[0]
    for col in vehicle_cols:
        external_annual_benchmark.loc[2025, col] = float(latest_trailing_row[f"{col}_trailing4_share"])

    return external_annual_benchmark.sort_index()


def forecast_share_delta(history: pd.DataFrame, future_years: list[int]) -> pd.DataFrame:
    share_delta = history[vehicle_cols].diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*SHARE_DELTA_CLIP)
    avg_delta = share_delta.mean().reindex(vehicle_cols).fillna(0)
    current = history.loc[int(history.index.max()), vehicle_cols].astype(float).copy()
    preds = {}
    horizon = max(1, future_years[-1] - future_years[0] + 1)
    for step, year in enumerate(future_years, start=1):
        damping = 1 - (1 - DAMPING_END_FACTOR) * (step / horizon)
        next_share = (current + avg_delta * damping).clip(lower=0)
        next_share = next_share / next_share.sum() if next_share.sum() > 0 else current.copy()
        next_share["electric"] = min(float(next_share["electric"]), MAX_ELECTRIC_ENTRY_SHARE)
        non_electric = next_share.drop("electric")
        if non_electric.sum() > 0:
            next_share.loc[non_electric.index] = non_electric * ((1 - next_share["electric"]) / non_electric.sum())
        preds[year] = next_share.copy()
        current = next_share.copy()
    return pd.DataFrame(preds).T


def forecast_naive(history: pd.DataFrame, future_years: list[int]) -> pd.DataFrame:
    last = history.loc[int(history.index.max()), vehicle_cols].astype(float)
    return pd.DataFrame({year: last for year in future_years}).T


def forecast_hybrid_delta(history: pd.DataFrame, future_years: list[int]) -> pd.DataFrame:
    delta = history[vehicle_cols].diff().replace([np.inf, -np.inf], 0).fillna(0).clip(*SHARE_DELTA_CLIP)
    avg_delta = delta.mean().reindex(vehicle_cols).fillna(0)
    current = history.loc[int(history.index.max()), vehicle_cols].astype(float).copy()
    preds = {}
    horizon = max(1, future_years[-1] - future_years[0] + 1)

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

        next_share = next_share.clip(lower=0)
        next_share = next_share / next_share.sum() if next_share.sum() > 0 else current.copy()
        next_share["electric"] = min(float(next_share["electric"]), MAX_ELECTRIC_ENTRY_SHARE)
        non_electric = next_share.drop("electric")
        if non_electric.sum() > 0:
            next_share.loc[non_electric.index] = non_electric * ((1 - next_share["electric"]) / non_electric.sum())
        preds[year] = next_share.copy()
        current = next_share.copy()

    return pd.DataFrame(preds).T


def long_errors(pred: pd.DataFrame, obs: pd.DataFrame, model_name: str, validation_name: str) -> pd.DataFrame:
    rows = []
    for year in pred.index:
        for col in vehicle_cols:
            predicted = float(pred.loc[year, col])
            observed = float(obs.loc[year, col])
            rows.append(
                {
                    "validation": validation_name,
                    "model": model_name,
                    "year": int(year),
                    "vehicle_type": col,
                    "predicted_share": predicted,
                    "observed_share": observed,
                    "error": predicted - observed,
                    "abs_error": abs(predicted - observed),
                    "squared_error": (predicted - observed) ** 2,
                }
            )
    return pd.DataFrame(rows)


def metrics_by_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    summary = (
        df.groupby(group_cols)
        .agg(
            mae=("abs_error", "mean"),
            rmse=("squared_error", lambda x: float(np.sqrt(np.mean(x)))),
            mean_error=("error", "mean"),
            max_abs_error=("abs_error", "max"),
            n=("abs_error", "size"),
        )
        .reset_index()
    )
    return summary


def add_share_plot(ax, observed, predicted, title):
    for col in vehicle_cols:
        ax.plot(observed.index, observed[col], marker="o", linewidth=2.0, label=f"Observed {col}")
        ax.plot(predicted.index, predicted[col], marker="s", linestyle="--", label=f"Predicted {col}")
    ax.set_title(title)
    ax.set_xlabel("Year")
    ax.set_ylabel("Share")


def main():
    sns.set_theme(style="whitegrid")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    observed = build_external_annual_benchmark(EXTERNAL_FILE)
    observed.to_csv(OUTPUT_DIR / "observed_sales_share_2017_2025.csv")

    # Main multi-year backtest: train through 2020, forecast 2021-2025.
    train_end_year = 2020
    forecast_years = list(range(2021, 2026))
    train_hist = observed.loc[2017:train_end_year]

    delta_pred = forecast_share_delta(train_hist, forecast_years)
    hybrid_pred = forecast_hybrid_delta(train_hist, forecast_years)
    naive_pred = forecast_naive(train_hist, forecast_years)
    actual = observed.loc[forecast_years, vehicle_cols]

    delta_errors = long_errors(delta_pred, actual, "share_delta", "train_to_2020_forecast_2021_2025")
    hybrid_errors = long_errors(hybrid_pred, actual, "hybrid_delta", "train_to_2020_forecast_2021_2025")
    naive_errors = long_errors(naive_pred, actual, "naive_last_share", "train_to_2020_forecast_2021_2025")
    multi_year_errors = pd.concat([delta_errors, hybrid_errors, naive_errors], ignore_index=True)

    # Rolling one-year-ahead validation.
    rolling_rows = []
    for target_year in range(2021, 2026):
        hist = observed.loc[2017 : target_year - 1]
        pred = forecast_share_delta(hist, [target_year])
        rolling_rows.append(long_errors(pred, observed.loc[[target_year], vehicle_cols], "share_delta", "rolling_one_step"))
        pred_hybrid = forecast_hybrid_delta(hist, [target_year])
        rolling_rows.append(long_errors(pred_hybrid, observed.loc[[target_year], vehicle_cols], "hybrid_delta", "rolling_one_step"))
    rolling_errors = pd.concat(rolling_rows, ignore_index=True)

    all_errors = pd.concat([multi_year_errors, rolling_errors], ignore_index=True)
    all_errors.to_csv(OUTPUT_DIR / "predicted_vs_observed_sales_share_long.csv", index=False)

    overall_summary = metrics_by_group(all_errors, ["validation", "model"])
    by_type_summary = metrics_by_group(all_errors, ["validation", "model", "vehicle_type"])
    by_year_summary = metrics_by_group(all_errors, ["validation", "model", "year"])

    overall_summary.to_csv(OUTPUT_DIR / "validation_overall_summary.csv", index=False)
    by_type_summary.to_csv(OUTPUT_DIR / "validation_by_vehicle_type.csv", index=False)
    by_year_summary.to_csv(OUTPUT_DIR / "validation_by_year.csv", index=False)

    # Save wide comparison for the main backtest.
    wide_compare = actual.copy()
    wide_compare.columns = [f"observed_{c}" for c in actual.columns]
    for col in vehicle_cols:
        wide_compare[f"predicted_share_delta_{col}"] = delta_pred[col]
        wide_compare[f"predicted_hybrid_delta_{col}"] = hybrid_pred[col]
        wide_compare[f"predicted_naive_{col}"] = naive_pred[col]
    wide_compare.to_csv(OUTPUT_DIR / "train2020_forecast2021_2025_comparison.csv")

    # Plots
    fig, axes = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
    axes = axes.flatten()
    for ax, col in zip(axes, vehicle_cols):
        ax.plot(actual.index, actual[col], marker="o", linewidth=2, label="Observed")
        ax.plot(delta_pred.index, delta_pred[col], marker="s", linestyle="--", label="Predicted: share-delta")
        ax.plot(hybrid_pred.index, hybrid_pred[col], marker="^", linestyle=":", label="Predicted: hybrid-delta")
        ax.set_title(col)
        ax.set_ylabel("Sales share")
        ax.legend()
    plt.suptitle("Observed vs Predicted Sales Share by Vehicle Type (Train Through 2020)", y=1.02)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "observed_vs_predicted_sales_share_by_type.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(actual.index, actual["electric"], marker="o", linewidth=2.5, label="Observed EV sales share")
    ax.plot(delta_pred.index, delta_pred["electric"], marker="s", linestyle="--", linewidth=2.0, label="Predicted EV sales share: share-delta")
    ax.plot(hybrid_pred.index, hybrid_pred["electric"], marker="^", linestyle=":", linewidth=2.0, label="Predicted EV sales share: hybrid-delta")
    ax.plot(naive_pred.index, naive_pred["electric"], marker="^", linestyle=":", linewidth=2.0, label="Naive EV sales share")
    ax.set_title("EV Sales Share Backtest: Forecast 2021-2025 Using Data Through 2020")
    ax.set_xlabel("Year")
    ax.set_ylabel("Sales share")
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "ev_sales_share_backtest.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    plot_df = by_type_summary[by_type_summary["validation"] == "train_to_2020_forecast_2021_2025"].copy()
    sns.barplot(data=plot_df, x="vehicle_type", y="mae", hue="model", ax=ax)
    ax.set_title("Backtest MAE by Vehicle Type (Forecast 2021-2025)")
    ax.set_xlabel("Vehicle type")
    ax.set_ylabel("MAE in sales share")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "mae_by_vehicle_type.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    plot_df = by_year_summary[by_year_summary["validation"] == "train_to_2020_forecast_2021_2025"].copy()
    sns.lineplot(data=plot_df, x="year", y="mae", hue="model", marker="o", ax=ax)
    ax.set_title("Backtest MAE by Forecast Year")
    ax.set_xlabel("Year")
    ax.set_ylabel("MAE in sales share")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "mae_by_year.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    print("Overall validation summary")
    print(overall_summary.to_string(index=False))
    print("\nModel validation outputs written to:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()
