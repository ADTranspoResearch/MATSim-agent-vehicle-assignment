#!/usr/bin/env python3
"""
Create an FSA-level electric-vehicle share heatmap for a selected year/scenario.

This script reads the existing predicted-share CSVs in:
  data/vehicles/predicted_share/
"""

from __future__ import annotations

import _setup_path  # pylint: disable=unused-import
import argparse
import csv
import math
import os
import sys
from pathlib import Path

from matsim_vehicle_type.config import SCN_CASE, SCN_YEAR


# ---------------------------------------------------------------------------
# File configuration
# ---------------------------------------------------------------------------
# This script is intended to live in:
#   MATSim-agent-vehicle-assignment/data_post-processing/
#
# PROJECT_ROOT is therefore the parent directory of data_post-processing.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_YEAR = SCN_YEAR
DEFAULT_SCENARIO = SCN_CASE

PREDICTED_SHARE_DIR = PROJECT_ROOT / "data" / "vehicles" / "predicted_share"
FSA_GIS_FILE = PROJECT_ROOT / "data" / "FSA" / "quebec_fsa" / "quebec_fsa.shp"

# Results will be written to data_post-processing/results/.
OUTPUT_DIR = SCRIPT_DIR / "results"
EV_SHARE_COLUMN = "electric"
FOCUS_FSA_CODES = ("G1K", "G1L", "G1R", "G1S")
FOCUS_ZOOM = 0.20
TOP_LABEL_COUNT = 5


def rounded_share_limit(max_share: float) -> float:
    if max_share <= 0:
        return 0.01
    if max_share <= 0.05:
        step = 0.005
    elif max_share <= 0.2:
        step = 0.02
    else:
        step = 0.1
    return min(1.0, math.ceil(max_share / step) * step)


def colorbar_limit_for_year(year: int, max_share: float) -> float:
    if year >= 2035:
        return 1.0
    return rounded_share_limit(max_share)


def colormap_for_year(year: int, linear_segmented_colormap):
    if year == 2020:
        return linear_segmented_colormap.from_list(
            "ev_share_2020_cyan_blue",
            ["#f2fbff", "#b9e6f2", "#5cc3d8", "#0089a8"],
        )
    return "Blues"


def format_share_label(value: float) -> str:
    if value < 0.05:
        return f"{value:.2%}"
    return f"{value:.1%}"


def predicted_share_file_for(year: int, scenario: str) -> Path:
    return PREDICTED_SHARE_DIR / f"fsa_vehicle_share_{year}_{scenario}.csv"


def validate_input_files(predicted_share_file: Path) -> None:
    """Fail early with a clear message if a configured input file is absent."""
    missing = [
        path
        for path in (predicted_share_file, FSA_GIS_FILE)
        if not path.is_file()
    ]
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Input file(s) not found:\n{formatted}")


def write_ev_share_csv(input_path: Path, output_path: Path) -> tuple[int, float]:
    rows: list[dict[str, float | str]] = []
    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        required_columns = {"fsa", EV_SHARE_COLUMN}
        if not required_columns.issubset(fieldnames):
            raise ValueError(
                f"{input_path} must contain columns {sorted(required_columns)}; "
                f"got {fieldnames}"
            )

        for row in reader:
            fsa = (row.get("fsa") or "").strip()
            if not fsa:
                continue
            ev_share = float(row[EV_SHARE_COLUMN])
            rows.append(
                {
                    "fsa": fsa,
                    "ev_share": ev_share,
                    "ev_share_percent": ev_share * 100,
                }
            )

    rows.sort(key=lambda row: str(row["fsa"]))
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["fsa", "ev_share", "ev_share_percent"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "fsa": row["fsa"],
                    "ev_share": f"{float(row['ev_share']):.8f}",
                    "ev_share_percent": f"{float(row['ev_share_percent']):.8f}",
                }
            )

    mean_share = (
        sum(float(row["ev_share"]) for row in rows) / len(rows)
        if rows
        else 0.0
    )
    return len(rows), mean_share


def read_ev_share_csv(path: Path) -> dict[str, float]:
    result: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row.get("fsa") or "").strip()
            if fsa:
                result[fsa] = float(row["ev_share"])
    return result


def plot_fsa_ev_share_map(
    csv_path: Path,
    output_path: Path,
    year: int,
    scenario: str,
) -> None:
    matplotlib_config_dir = OUTPUT_DIR / ".matplotlib"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))

    try:
        import geopandas as gpd
        import matplotlib
        from matplotlib.colors import LinearSegmentedColormap
        from matplotlib.ticker import MaxNLocator, PercentFormatter

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "Plotting requires geopandas and matplotlib."
        ) from exc

    if not FSA_GIS_FILE.is_file():
        raise FileNotFoundError(f"FSA GIS file not found: {FSA_GIS_FILE}")
    if not csv_path.is_file():
        raise FileNotFoundError(f"FSA EV-share CSV not found: {csv_path}")

    gdf = gpd.read_file(FSA_GIS_FILE)
    if "PRUID" in gdf.columns:
        gdf = gdf[gdf["PRUID"].astype(str) == "24"]

    ev_share_by_fsa = read_ev_share_csv(csv_path)
    merged = gdf.copy()
    merged["fsa"] = merged["CFSAUID"]
    merged["ev_share"] = merged["CFSAUID"].map(ev_share_by_fsa)
    with_data = merged[merged["ev_share"].notna()].copy()
    if with_data.empty:
        examples = ", ".join(sorted(ev_share_by_fsa)[:5]) or "none"
        raise ValueError(
            "No EV-share FSA values matched the Quebec FSA shapefile. "
            f"Input FSA examples: {examples}"
        )

    focus = with_data[with_data["CFSAUID"].isin(FOCUS_FSA_CODES)]
    if focus.empty:
        focus = with_data

    minx, miny, maxx, maxy = focus.total_bounds
    center_x = (minx + maxx) / 2
    center_y = (miny + maxy) / 2
    half_width = (maxx - minx) / (2 * FOCUS_ZOOM)
    half_height = (maxy - miny) / (2 * FOCUS_ZOOM)
    xlim = (center_x - half_width, center_x + half_width)
    ylim = (center_y - half_height, center_y + half_height)

    fig, ax = plt.subplots(1, 1, figsize=(7, 10))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    colorbar_max = colorbar_limit_for_year(year, float(with_data["ev_share"].max()))
    with_data.plot(
        column="ev_share",
        ax=ax,
        legend=True,
        cmap=colormap_for_year(year, LinearSegmentedColormap),
        edgecolor="white",
        linewidth=0.5,
        vmin=0,
        vmax=colorbar_max,
        legend_kwds={"label": "", "shrink": 0.65},
    )
    colorbar_ax = fig.axes[-1]
    colorbar_ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    colorbar_ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")

    label_x_margin = (xlim[1] - xlim[0]) * 0.04
    label_y_margin = (ylim[1] - ylim[0]) * 0.04
    label_rows = with_data.copy()
    label_points = label_rows.geometry.representative_point()
    label_rows["label_x"] = label_points.x
    label_rows["label_y"] = label_points.y
    label_rows = label_rows[
        label_rows["label_x"].between(*xlim)
        & label_rows["label_y"].between(*ylim)
    ]
    label_rows = label_rows.nlargest(TOP_LABEL_COUNT, "ev_share")
    for _, row in label_rows.iterrows():
        label_x = min(
            max(row["label_x"], xlim[0] + label_x_margin),
            xlim[1] - label_x_margin,
        )
        label_y = min(
            max(row["label_y"], ylim[0] + label_y_margin),
            ylim[1] - label_y_margin,
        )
        ax.annotate(
            f"{row['CFSAUID']}\n{format_share_label(row['ev_share'])}",
            xy=(label_x, label_y),
            ha="center",
            va="center",
            fontsize=8,
            color="black",
            bbox={
                "boxstyle": "round,pad=0.2",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.8,
            },
        )

    ax.axis("off")
    plt.tight_layout()
    fig.savefig(
        output_path,
        dpi=150,
        bbox_inches="tight",
        pad_inches=0.02,
        facecolor="white",
    )
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an FSA EV-share CSV and heatmap for a year/scenario."
    )
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Only regenerate the heatmap from an existing results CSV.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    year = args.year
    scenario = args.scenario

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    input_file = predicted_share_file_for(year, scenario)
    fsa_output = OUTPUT_DIR / f"ev_share_by_fsa_{year}_{scenario}.csv"
    map_output = OUTPUT_DIR / f"ev_share_by_fsa_{year}_{scenario}.png"

    if args.plot_only:
        plot_fsa_ev_share_map(fsa_output, map_output, year, scenario)
        print(f"Wrote {map_output}", file=sys.stderr)
        return 0

    validate_input_files(input_file)

    print(f"Reading {input_file}", file=sys.stderr)
    fsa_count, mean_share = write_ev_share_csv(input_file, fsa_output)
    plot_fsa_ev_share_map(fsa_output, map_output, year, scenario)

    print(f"Wrote {fsa_output}", file=sys.stderr)
    print(f"Wrote {map_output}", file=sys.stderr)
    print(f"FSA rows mapped from predicted shares: {fsa_count:,}", file=sys.stderr)
    print(f"Mean FSA EV share: {mean_share:.4%}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
