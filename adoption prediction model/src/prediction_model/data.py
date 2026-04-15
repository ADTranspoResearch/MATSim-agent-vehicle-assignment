from pathlib import Path

import pandas as pd

from .config import CACHE_DIR, EXTERNAL_FILE, POPULATION_FILE, QUARTER_ORDER, VEHICLE_TYPES


def load_vehicle_counts(cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    return pd.read_pickle(cache_dir / "saq_vehicle_counts.pkl")


def load_entry_counts(cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    return pd.read_pickle(cache_dir / "saq_entry_counts.pkl")


def load_entry_full(cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    return pd.read_pickle(cache_dir / "saq_entry_full.pkl")


def build_external_annual_benchmark(path: Path = EXTERNAL_FILE) -> pd.DataFrame:
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

    def qcol(body_class: str, fuel_type: str) -> pd.Series:
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
    counts["quarter_num"] = counts["quarter"].map({quarter: idx + 1 for idx, quarter in enumerate(QUARTER_ORDER)})

    trailing = counts.sort_values(["year", "quarter_num"]).reset_index(drop=True)
    for col in VEHICLE_TYPES + ["total_registrations"]:
        trailing[f"{col}_trailing4"] = trailing[col].rolling(4, min_periods=4).sum()

    annual_counts = counts.groupby("year")[VEHICLE_TYPES + ["total_registrations"]].sum()
    annual = annual_counts[VEHICLE_TYPES].div(annual_counts["total_registrations"], axis=0)

    row_2025 = trailing.loc[(trailing["year"] == 2025) & (trailing["quarter"] == "T1")].iloc[0]
    for col in VEHICLE_TYPES:
        annual.loc[2025, col] = row_2025[f"{col}_trailing4"] / row_2025["total_registrations_trailing4"]

    return annual.sort_index()


def load_population_q1_series(path: Path = POPULATION_FILE) -> pd.Series:
    population_raw = pd.read_csv(path, skiprows=7)
    population_quebec = population_raw[population_raw["Geography"] == "Quebec"].copy()
    population_quebec = population_quebec.drop(
        columns=[col for col in population_quebec.columns if str(col).startswith("Unnamed")],
        errors="ignore",
    )
    pop_row = population_quebec.iloc[0].drop(labels=["Geography"])
    pop_series = pd.to_numeric(pop_row.astype(str).str.replace(",", "", regex=False), errors="coerce").dropna()

    population_q1 = {}
    for col, value in pop_series.items():
        col = str(col)
        if col.startswith("Q1 "):
            population_q1[int(col.split()[-1])] = float(value)
    return pd.Series(population_q1).sort_index()
