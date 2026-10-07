#!/usr/bin/env python3
"""
Plot Quebec City new-vehicle EV share across adoption scenarios.
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

DEFAULT_FSA = "H0H"
START_YEAR = 2021
END_YEAR = 2035
LABEL_YEARS = {2035}

INPUT_DIR = PROJECT_ROOT / "data" / "vehicles" / "val_outputs"
OUTPUT_DIR = SCRIPT_DIR / "results"
NEW_VEHICLE_SECTION = "# ---------- Predicted New Vehicle Mix ----------"

SCENARIOS = [
    ("BAU", "BAU"),
    ("ACCELERATED_ADOPTION", "Accelerated adoption"),
    ("DELAYED_ADOPTION", "Delayed adoption"),
    ("POLICY_ALIGNED", "Policy-aligned"),
]

SCENARIO_STYLES = {
    "BAU": {"color": "#2a9d8f", "marker": "o", "linestyle": "-"},
    "ACCELERATED_ADOPTION": {"color": "#457b9d", "marker": "s", "linestyle": "-"},
    "DELAYED_ADOPTION": {"color": "#e76f51", "marker": "^", "linestyle": "--"},
    "POLICY_ALIGNED": {"color": "#6a4c93", "marker": "D", "linestyle": "-."},
}

LABEL_OFFSETS = {
    "BAU": {"x": -0.06, "y": -0.034, "va": "top"},
    "ACCELERATED_ADOPTION": {"x": 0.0, "y": 0.024, "va": "bottom"},
    "DELAYED_ADOPTION": {"x": 0.06, "y": -0.028, "va": "top"},
    "POLICY_ALIGNED": {"x": 0.08, "y": 0.020, "va": "bottom"},
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


def subset_series(
    years: list[int],
    values: list[float],
    start_year: int,
    end_year: int,
) -> tuple[list[int], list[float]]:
    selected_indexes = [
        index for index, year in enumerate(years) if start_year <= year <= end_year
    ]
    selected_years = [years[index] for index in selected_indexes]
    selected_values = [values[index] for index in selected_indexes]

    expected_years = list(range(start_year, end_year + 1))
    if selected_years != expected_years:
        raise ValueError(
            f"Expected years {start_year}-{end_year}; got {selected_years}"
        )

    return selected_years, selected_values


def read_scenario_ev_share(
    scenario: str,
    fsa: str,
    start_year: int,
    end_year: int,
) -> tuple[list[int], list[float]]:
    input_path = input_file_for(scenario, fsa)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    years, values = parse_section(input_path, NEW_VEHICLE_SECTION)
    if "electric" not in values:
        raise ValueError(f"No electric row found in {input_path}")
    return subset_series(years, values["electric"], start_year, end_year)


def plot_ev_share(
    scenario_series: dict[str, tuple[str, list[int], list[float]]],
    output_path: Path,
    start_year: int,
    end_year: int,
) -> None:
    matplotlib_config_dir = OUTPUT_DIR / ".matplotlib"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))

    try:
        import matplotlib

        matplotlib.use("Agg")
        matplotlib.rcParams["font.family"] = ["Times New Roman", "Times", "serif"]
        import matplotlib.pyplot as plt
        from matplotlib.ticker import PercentFormatter
    except ImportError as exc:
        raise RuntimeError("Plotting requires matplotlib.") from exc

    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    for scenario, (label, years, values) in scenario_series.items():
        style = SCENARIO_STYLES[scenario]
        ax.plot(
            years,
            values,
            label=label,
            color=style["color"],
            marker=style["marker"],
            linestyle=style["linestyle"],
            linewidth=1.8,
            markersize=4.5,
        )
        for year, share in zip(years, values):
            if year not in LABEL_YEARS:
                continue

            offset = LABEL_OFFSETS[scenario]

            ax.text(
                year + offset["x"],
                min(max(share + offset["y"], 0.018), 0.982),
                f"{share * 100:.1f}%",
                color=style["color"],
                fontsize=7.5,
                ha="center",
                va=offset["va"],
            )

    ax.set_xlabel("Year")
    ax.set_ylabel("New vehicle EV share")
    ax.set_xlim(start_year - 0.25, end_year + 0.25)
    ax.set_ylim(0, 1.0)
    ax.set_xticks(list(range(start_year, end_year + 1, 2)))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    ax.grid(axis="y", color="#d9dee3", linewidth=0.8, alpha=0.85)
    ax.grid(axis="x", color="#edf0f2", linewidth=0.6, alpha=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="upper left", frameon=False)

    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a Quebec City line chart comparing new-vehicle EV share "
            "from 2021 to 2035 across adoption scenarios."
        )
    )
    parser.add_argument("--fsa", default=DEFAULT_FSA)
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for output PNG files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    scenario_series: dict[str, tuple[str, list[int], list[float]]] = {}
    for scenario, label in SCENARIOS:
        years, values = read_scenario_ev_share(
            scenario, args.fsa, args.start_year, args.end_year
        )
        scenario_series[scenario] = (label, years, values)
        print(f"Read {input_file_for(scenario, args.fsa)}", file=sys.stderr)

    output_path = (
        args.output_dir
        / f"qcity_new_vehicle_ev_share_by_scenario_{args.start_year}_{args.end_year}.png"
    )
    plot_ev_share(scenario_series, output_path, args.start_year, args.end_year)

    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
