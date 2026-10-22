#!/usr/bin/env python3
"""
Plot Quebec City new-vehicle market share and fleet mix from validation output.

The source CSV contains three stacked tables:
  1. fleet counts
  2. fleet share percentages
  3. predicted new vehicle mix
"""

from __future__ import annotations

import _setup_path  # pylint: disable=unused-import
import argparse
import csv
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_SCENARIO = "bau"
DEFAULT_FSA = "H0H"
START_YEAR = 2021
END_YEAR = 2040

INPUT_DIR = PROJECT_ROOT / "data" / "vehicles" / "val_outputs"
OUTPUT_DIR = SCRIPT_DIR / "results"

FLEET_SHARE_SECTION = "# ---------- Fleet Share Percentages ----------"
NEW_VEHICLE_SECTION = "# ---------- Predicted New Vehicle Mix ----------"

EV_BODY_TYPE_ORDER = [
    "ev_passenger_cars",
    "ev_multi_purpose_vehicles",
    "ev_van_pickup",
]

NON_EV_VEHICLE_TYPE_ORDER = [
    "hev_sedan",
    "hev_suv",
    "ice_sedan",
    "ice_suv",
    "ice_van/pickup",
]

PLOT_VEHICLE_TYPE_ORDER = EV_BODY_TYPE_ORDER + NON_EV_VEHICLE_TYPE_ORDER

VEHICLE_TYPE_LABELS = {
    "ev_passenger_cars": "EV sedan",
    "ev_multi_purpose_vehicles": "EV SUV",
    "ev_van_pickup": "EV van/pickup",
    "hev_sedan": "HEV sedan",
    "hev_suv": "HEV SUV",
    "ice_sedan": "ICE sedan",
    "ice_suv": "ICE SUV",
    "ice_van/pickup": "ICE van/pickup",
}

VEHICLE_TYPE_COLORS = {
    "ev_passenger_cars": "#0f766e",
    "ev_multi_purpose_vehicles": "#38b2ac",
    "ev_van_pickup": "#a7f3d0",
    "hev_sedan": "#8ab17d",
    "hev_suv": "#e9c46a",
    "ice_sedan": "#f4a261",
    "ice_suv": "#e76f51",
    "ice_van/pickup": "#5f6c7b",
}

# Quebec battery-electric registration counts by body type from
# data/2310030801-eng.numbers, Statistics Canada Table 23-10-0308-01:
# https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2310030801
# Shares are normalized across these three requested categories. Years after
# 2024 use 2024 shares.
EV_BODY_TYPE_COUNTS = {
    2017: {
        "ev_passenger_cars": 6379.0,
        "ev_multi_purpose_vehicles": 1068.0,
        "ev_van_pickup": 5.0,
    },
    2018: {
        "ev_passenger_cars": 11758.0,
        "ev_multi_purpose_vehicles": 1681.0,
        "ev_van_pickup": 5.0,
    },
    2019: {
        "ev_passenger_cars": 22593.0,
        "ev_multi_purpose_vehicles": 3745.0,
        "ev_van_pickup": 6.0,
    },
    2020: {
        "ev_passenger_cars": 34928.0,
        "ev_multi_purpose_vehicles": 7592.0,
        "ev_van_pickup": 5.0,
    },
    2021: {
        "ev_passenger_cars": 45349.0,
        "ev_multi_purpose_vehicles": 16412.0,
        "ev_van_pickup": 4.0,
    },
    2022: {
        "ev_passenger_cars": 55216.0,
        "ev_multi_purpose_vehicles": 29997.0,
        "ev_van_pickup": 438.0,
    },
    2023: {
        "ev_passenger_cars": 67734.0,
        "ev_multi_purpose_vehicles": 55811.0,
        "ev_van_pickup": 2493.0,
    },
    2024: {
        "ev_passenger_cars": 78599.0,
        "ev_multi_purpose_vehicles": 114742.0,
        "ev_van_pickup": 6398.0,
    },
}


def input_file_for(scenario: str, fsa: str) -> Path:
    return INPUT_DIR / scenario / f"{fsa}_predicted_fleet_mix.csv"


def parse_section(path: Path, marker: str) -> tuple[list[int], dict[str, list[float]]]:
    years: list[int] | None = None
    values: dict[str, list[float]] = {}
    in_section = False

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        for row in reader:
            if not row:
                if in_section and values:
                    break
                continue

            first_cell = row[0].strip()
            if first_cell.startswith("#"):
                if first_cell == marker:
                    in_section = True
                    years = None
                    values = {}
                elif in_section:
                    break
                continue

            if not in_section:
                continue

            if years is None:
                year_cells = row[1:] if first_cell in {"", "vehicle_type"} else row
                years = [int(value) for value in year_cells]
                continue

            vehicle_type = first_cell
            if vehicle_type:
                values[vehicle_type] = [float(value) for value in row[1:]]

    if years is None or not values:
        raise ValueError(f"Could not find section {marker!r} in {path}")

    return years, values


def subset_years(
    years: list[int],
    values: dict[str, list[float]],
    start_year: int,
    end_year: int,
) -> tuple[list[int], dict[str, list[float]]]:
    selected_indexes = [
        index for index, year in enumerate(years) if start_year <= year <= end_year
    ]
    selected_years = [years[index] for index in selected_indexes]
    selected_values = {
        vehicle_type: [series[index] for index in selected_indexes]
        for vehicle_type, series in values.items()
    }

    expected_years = list(range(start_year, end_year + 1))
    if selected_years != expected_years:
        raise ValueError(
            f"Expected years {start_year}-{end_year}; got {selected_years}"
        )

    return selected_years, selected_values


def ev_body_type_shares_for(year: int) -> dict[str, float]:
    count_year = min(max(year, min(EV_BODY_TYPE_COUNTS)), max(EV_BODY_TYPE_COUNTS))
    counts = EV_BODY_TYPE_COUNTS[count_year]
    total = sum(counts.values())
    return {
        vehicle_type: counts[vehicle_type] / total
        for vehicle_type in EV_BODY_TYPE_ORDER
    }


def split_electric_by_body_type(
    years: list[int],
    values: dict[str, list[float]],
) -> dict[str, list[float]]:
    if "electric" not in values:
        raise ValueError("Missing vehicle type: electric")

    split_values = {
        vehicle_type: []
        for vehicle_type in EV_BODY_TYPE_ORDER
    }
    for year, ev_share in zip(years, values["electric"]):
        shares = ev_body_type_shares_for(year)
        for vehicle_type in EV_BODY_TYPE_ORDER:
            split_values[vehicle_type].append(ev_share * shares[vehicle_type])

    for vehicle_type in NON_EV_VEHICLE_TYPE_ORDER:
        if vehicle_type not in values:
            raise ValueError(f"Missing vehicle type: {vehicle_type}")
        split_values[vehicle_type] = values[vehicle_type]

    return split_values


def ordered_series(values: dict[str, list[float]]) -> tuple[list[str], list[list[float]]]:
    missing = [
        vehicle_type
        for vehicle_type in PLOT_VEHICLE_TYPE_ORDER
        if vehicle_type not in values
    ]
    if missing:
        raise ValueError(f"Missing vehicle types: {missing}")

    return PLOT_VEHICLE_TYPE_ORDER, [
        values[vehicle_type] for vehicle_type in PLOT_VEHICLE_TYPE_ORDER
    ]


def add_grouped_legend(fig) -> None:
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    ev_handles = [
        Patch(
            facecolor=VEHICLE_TYPE_COLORS[vehicle_type],
            label=VEHICLE_TYPE_LABELS[vehicle_type],
        )
        for vehicle_type in EV_BODY_TYPE_ORDER
    ]
    ice_handles = [
        Patch(
            facecolor=VEHICLE_TYPE_COLORS[vehicle_type],
            label=VEHICLE_TYPE_LABELS[vehicle_type],
        )
        for vehicle_type in ("ice_sedan", "ice_suv", "ice_van/pickup")
    ]
    hev_handles = [
        Patch(
            facecolor=VEHICLE_TYPE_COLORS[vehicle_type],
            label=VEHICLE_TYPE_LABELS[vehicle_type],
        )
        for vehicle_type in ("hev_sedan", "hev_suv")
    ]
    ev_point_handles = [
        Line2D(
            [0],
            [0],
            color="#0f766e",
            marker="o",
            markersize=5,
            linewidth=1.2,
            label="Total EV data points",
        )
    ]

    legend_specs = [
        (ev_handles, 0.22),
        (ice_handles, 0.45),
        (hev_handles, 0.64),
        (ev_point_handles, 0.83),
    ]
    for handles, x_anchor in legend_specs:
        fig.legend(
            handles=handles,
            loc="lower center",
            bbox_to_anchor=(x_anchor, 0.055),
            ncol=1,
            frameon=False,
            handlelength=1.8,
            handletextpad=0.6,
        )


def plot_share_area(
    years: list[int],
    values: dict[str, list[float]],
    title: str,
    ylabel: str,
    output_path: Path,
) -> None:
    matplotlib_config_dir = OUTPUT_DIR / ".matplotlib"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))

    try:
        import matplotlib

        matplotlib.use("Agg")
        matplotlib.rcParams["font.family"] = [
            "Arial",
            "Helvetica",
            "DejaVu Sans",
            "sans-serif",
        ]
        import matplotlib.pyplot as plt
        from matplotlib.ticker import PercentFormatter
    except ImportError as exc:
        raise RuntimeError("Plotting requires matplotlib.") from exc

    plot_values = split_electric_by_body_type(years, values)
    vehicle_types, series = ordered_series(plot_values)
    labels = [VEHICLE_TYPE_LABELS[vehicle_type] for vehicle_type in vehicle_types]
    colors = [VEHICLE_TYPE_COLORS[vehicle_type] for vehicle_type in vehicle_types]

    fig, ax = plt.subplots(figsize=(11, 7.0))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.stackplot(years, series, labels=labels, colors=colors, linewidth=0.0, alpha=0.96)
    ev_series = values["electric"]
    ax.plot(
        years,
        ev_series,
        color="#0f766e",
        marker="o",
        markersize=4.5,
        linewidth=1.2,
        label="Total EV data points",
        zorder=5,
    )
    for index, (year, share) in enumerate(zip(years, ev_series)):
        offset = 0.018 if index % 2 == 0 else -0.028
        vertical_alignment = "bottom" if offset > 0 else "top"
        horizontal_alignment = "right" if year == max(years) else "center"
        ax.text(
            year,
            min(max(share + offset, 0.018), 0.982),
            f"{share * 100:.1f}%",
            color="#0f4f4a",
            fontsize=8.5,
            ha=horizontal_alignment,
            va=vertical_alignment,
            zorder=6,
        )
    ax.set_xlabel("Year")
    ax.set_ylabel(ylabel)
    ax.set_xlim(min(years) - 0.25, max(years) + 0.25)
    ax.set_ylim(0, 1)
    ax.set_xticks(years[::2])
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    ax.grid(axis="y", color="#d9dee3", linewidth=0.8, alpha=0.85)
    ax.grid(axis="x", color="#edf0f2", linewidth=0.6, alpha=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    add_grouped_legend(fig)

    fig.tight_layout(rect=(0, 0.18, 1, 1))
    fig.savefig(
        output_path,
        dpi=180,
        bbox_inches="tight",
        pad_inches=0.04,
        facecolor="white",
    )
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create Quebec City 2021-2040 new-vehicle market share and fleet "
            "mix plots from an H0H predicted fleet mix CSV."
        )
    )
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--fsa", default=DEFAULT_FSA)
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional explicit input CSV path.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for output PNG files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input or input_file_for(args.scenario, args.fsa)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    fleet_years, fleet_values = parse_section(input_path, FLEET_SHARE_SECTION)
    new_years, new_values = parse_section(input_path, NEW_VEHICLE_SECTION)
    years, fleet_values = subset_years(
        fleet_years, fleet_values, args.start_year, args.end_year
    )
    new_years, new_values = subset_years(
        new_years, new_values, args.start_year, args.end_year
    )

    if years != new_years:
        raise ValueError("Fleet mix and new-vehicle mix use different year ranges.")

    year_range = f"{args.start_year}_{args.end_year}"
    scenario_label = args.scenario
    new_vehicle_output = (
        output_dir / f"qcity_new_vehicle_market_share_{year_range}_{scenario_label}.png"
    )
    fleet_mix_output = output_dir / f"qcity_fleet_mix_{year_range}_{scenario_label}.png"

    plot_share_area(
        years,
        new_values,
        f"Quebec City New Vehicle Market Share ({args.start_year}-{args.end_year}, {scenario_label})",
        "New vehicle market share",
        new_vehicle_output,
    )
    plot_share_area(
        years,
        fleet_values,
        f"Quebec City Fleet Mix ({args.start_year}-{args.end_year}, {scenario_label})",
        "Fleet share",
        fleet_mix_output,
    )

    print(f"Read {input_path}", file=sys.stderr)
    print(f"Wrote {new_vehicle_output}", file=sys.stderr)
    print(f"Wrote {fleet_mix_output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
