#!/usr/bin/env python3
"""
Summarize MATSim electric-vehicle mileage by agent and FSA.

The events file is parsed incrementally, so this script can process very large
.xml or .xml.gz files without loading them into memory.
"""

from __future__ import annotations

import _setup_path  # pylint: disable=unused-import
import csv
import gzip
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import IO, Iterator

from matsim_vehicle_type.config import SCN_CASE


# ---------------------------------------------------------------------------
# File configuration
# ---------------------------------------------------------------------------
# This script is intended to live in:
#   MATSim-agent-vehicle-assignment/data_post-processing/
#
# PROJECT_ROOT is therefore the parent directory of data_post-processing.
# No file paths need to be supplied in the terminal.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
YEAR = 2035

VEHICLES_FILE_NAME = f"vehicles_updated_{YEAR}_BAU.xml"
VEHICLES_FILE_DIR = PROJECT_ROOT / "output"
VEHICLES_FILE = VEHICLES_FILE_DIR / VEHICLES_FILE_NAME

NETWORK_FILE = PROJECT_ROOT / "data" / "MATSim" / "network" / "network_0409.xml"
EVENTS_FILE = (
    PROJECT_ROOT / "data" / "MATSim" / "events" / "output_events_100.xml.gz"
)
FSA_FILE = PROJECT_ROOT / "data" / "FSA" / "agent_id_fsa_table.csv"
FSA_GIS_FILE = PROJECT_ROOT / "data" / "FSA" / "quebec_fsa" / "quebec_fsa.shp"

# Results will be written to data_post-processing/results/.
OUTPUT_DIR = SCRIPT_DIR / "results"
ELECTRIC_TYPE = "electric"
ELECTRICITY_KWH_PER_KM = 0.2


def open_text(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def iter_elements(path: Path, wanted_tag: str) -> Iterator[ET.Element]:
    with open_text(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if local_name(elem.tag) == wanted_tag:
                yield elem
            elem.clear()


def read_electric_vehicles(path: Path, electric_type: str) -> set[str]:
    vehicles: set[str] = set()
    for elem in iter_elements(path, "vehicle"):
        if elem.get("type") == electric_type and elem.get("id") is not None:
            vehicles.add(elem.get("id"))  # type: ignore[arg-type]
    return vehicles


def read_link_lengths(path: Path) -> dict[str, float]:
    lengths: dict[str, float] = {}
    for elem in iter_elements(path, "link"):
        link_id = elem.get("id")
        length = elem.get("length")
        if link_id is not None and length is not None:
            lengths[link_id] = float(length)
    return lengths


def read_fsa_csv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []

        # Supported formats:
        #   agent_id,fsa
        #   ,CFSAUID       (pandas CSV with agent ID saved as an unnamed index)
        if {"agent_id", "fsa"}.issubset(fieldnames):
            agent_column, fsa_column = "agent_id", "fsa"
        elif "" in fieldnames and "CFSAUID" in fieldnames:
            agent_column, fsa_column = "", "CFSAUID"
        else:
            raise ValueError(
                f"{path} must contain either agent_id,fsa or an unnamed index "
                f"column plus CFSAUID; got {fieldnames}"
            )

        for row in reader:
            agent_id = (row.get(agent_column) or "").strip()
            fsa = (row.get(fsa_column) or "").strip()
            if agent_id:
                result[agent_id] = fsa or "UNKNOWN"
    return result


def summarize_events(
    path: Path,
    electric_vehicles: set[str],
    link_lengths: dict[str, float],
) -> tuple[dict[str, float], dict[str, int], int]:
    agent_metres: dict[str, float] = defaultdict(float)
    agent_links: dict[str, int] = defaultdict(int)
    missing_link_events = 0

    with open_text(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if local_name(elem.tag) != "event":
                elem.clear()
                continue

            event_type = (elem.get("type") or "").lower()
            vehicle = elem.get("vehicle")

            if event_type == "left link" and vehicle in electric_vehicles:
                link = elem.get("link")
                length = link_lengths.get(link or "")
                if length is None:
                    missing_link_events += 1
                else:
                    # Model invariant supplied by the user:
                    # vehicle ID is exactly the same as agent/person ID.
                    agent_id = vehicle
                    agent_metres[agent_id] += length
                    agent_links[agent_id] += 1

            elem.clear()

    return agent_metres, agent_links, missing_link_events


def write_agent_csv(
    path: Path,
    electric_agents: set[str],
    agent_metres: dict[str, float],
    agent_links: dict[str, int],
    fsa_by_agent: dict[str, str],
) -> None:
    # electric vehicle ID == agent ID; include agents with zero mileage too.
    agent_ids = set(agent_metres) | electric_agents
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["agent_id", "fsa", "distance_m", "distance_km", "traversed_links"]
        )
        for agent_id in sorted(agent_ids):
            metres = agent_metres.get(agent_id, 0.0)
            writer.writerow(
                [
                    agent_id,
                    fsa_by_agent.get(agent_id, "UNKNOWN"),
                    f"{metres:.3f}",
                    f"{metres / 1000:.6f}",
                    agent_links.get(agent_id, 0),
                ]
            )


def write_fsa_csv(
    path: Path,
    electric_agents: set[str],
    agent_metres: dict[str, float],
    fsa_by_agent: dict[str, str],
) -> None:
    fsa_metres: dict[str, float] = defaultdict(float)
    fsa_agents: dict[str, set[str]] = defaultdict(set)
    active_agents: dict[str, set[str]] = defaultdict(set)

    for agent_id in set(agent_metres) | electric_agents:
        fsa = fsa_by_agent.get(agent_id, "UNKNOWN")
        fsa_agents[fsa].add(agent_id)
        metres = agent_metres.get(agent_id, 0.0)
        fsa_metres[fsa] += metres
        if metres > 0:
            active_agents[fsa].add(agent_id)

    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "fsa",
                "electric_agents",
                "electric_agents_with_mileage",
                "total_distance_m",
                "total_distance_km",
                "electricity_kwh",
                "mean_km_per_electric_agent",
            ]
        )
        for fsa in sorted(fsa_agents):
            count = len(fsa_agents[fsa])
            metres = fsa_metres[fsa]
            distance_km = metres / 1000
            writer.writerow(
                [
                    fsa,
                    count,
                    len(active_agents[fsa]),
                    f"{metres:.3f}",
                    f"{distance_km:.6f}",
                    f"{distance_km * ELECTRICITY_KWH_PER_KM:.6f}",
                    f"{distance_km / count:.6f}" if count else "0.000000",
                ]
            )


def plot_fsa_electricity_map(csv_path: Path, output_path: Path) -> None:
    matplotlib_config_dir = OUTPUT_DIR / ".matplotlib"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))

    try:
        import geopandas as gpd
        import matplotlib
        import pandas as pd

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "Plotting requires geopandas, pandas, and matplotlib."
        ) from exc

    if not FSA_GIS_FILE.is_file():
        raise FileNotFoundError(f"FSA GIS file not found: {FSA_GIS_FILE}")
    if not csv_path.is_file():
        raise FileNotFoundError(f"FSA mileage CSV not found: {csv_path}")

    gdf = gpd.read_file(FSA_GIS_FILE)
    if "PRUID" in gdf.columns:
        gdf = gdf[gdf["PRUID"].astype(str) == "24"]

    df = pd.read_csv(csv_path)
    if "electricity_kwh" not in df.columns:
        df["electricity_kwh"] = (
            df["total_distance_km"].astype(float) * ELECTRICITY_KWH_PER_KM
        )

    merged = gdf.merge(
        df[["fsa", "electricity_kwh"]],
        left_on="CFSAUID",
        right_on="fsa",
        how="left",
    )

    with_data = merged[merged["electricity_kwh"].notna()].copy()

    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    merged.plot(
        ax=ax,
        color="lightgrey",
        edgecolor="white",
        linewidth=0.2,
    )
    with_data.plot(
        column="electricity_kwh",
        ax=ax,
        legend=True,
        cmap="YlOrRd",
        edgecolor="white",
        linewidth=0.5,
        legend_kwds={"label": "Electricity use (kWh)", "shrink": 0.65},
    )

    ax.set_title(
        f"Electricity Use by FSA - Quebec ({ELECTRICITY_KWH_PER_KM:g} kWh/km)",
        fontsize=14,
    )
    if not with_data.empty:
        minx, miny, maxx, maxy = with_data.total_bounds
        x_padding = (maxx - minx) * 0.15
        y_padding = (maxy - miny) * 0.15
        ax.set_xlim(minx - x_padding, maxx + x_padding)
        ax.set_ylim(miny - y_padding, maxy + y_padding)

    label_points = with_data.geometry.representative_point()
    for (_, row), point in zip(with_data.iterrows(), label_points):
        ax.annotate(
            row["CFSAUID"],
            xy=(point.x, point.y),
            fontsize=7,
            ha="center",
            va="center",
            color="black",
        )

    ax.axis("off")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def validate_input_files() -> None:
    """Fail early with a clear message if a configured input file is absent."""
    missing = [
        path
        for path in (VEHICLES_FILE, NETWORK_FILE, EVENTS_FILE, FSA_FILE)
        if not path.is_file()
    ]
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Input file(s) not found:\n{formatted}")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fsa_output = OUTPUT_DIR / f"electric_mileage_by_fsa_{YEAR}_{SCN_CASE}.csv"
    map_output = OUTPUT_DIR / f"electricity_by_fsa_{YEAR}_{SCN_CASE}.png"
    if "--plot-only" in sys.argv[1:]:
        plot_fsa_electricity_map(fsa_output, map_output)
        print(f"Wrote {map_output}", file=sys.stderr)
        return 0

    validate_input_files()

    print("Reading electric vehicle IDs...", file=sys.stderr)
    electric_vehicles = read_electric_vehicles(VEHICLES_FILE, ELECTRIC_TYPE)
    print(f"Found {len(electric_vehicles):,} electric vehicles", file=sys.stderr)

    print("Reading network link lengths...", file=sys.stderr)
    link_lengths = read_link_lengths(NETWORK_FILE)
    print(f"Found {len(link_lengths):,} links", file=sys.stderr)

    fsa_by_agent = read_fsa_csv(FSA_FILE)

    print("Streaming events and accumulating mileage...", file=sys.stderr)
    agent_metres, agent_links, missing = summarize_events(
        EVENTS_FILE, electric_vehicles, link_lengths
    )
    electric_agents = electric_vehicles

    agent_output = OUTPUT_DIR / f"electric_mileage_by_agent_{YEAR}_{SCN_CASE}.csv"
    write_agent_csv(
        agent_output, electric_agents, agent_metres, agent_links, fsa_by_agent
    )
    write_fsa_csv(fsa_output, electric_agents, agent_metres, fsa_by_agent)
    plot_fsa_electricity_map(fsa_output, map_output)

    unmatched = len((set(agent_metres) | electric_agents) - set(fsa_by_agent))
    print(f"Wrote {agent_output}", file=sys.stderr)
    print(f"Wrote {fsa_output}", file=sys.stderr)
    print(f"Wrote {map_output}", file=sys.stderr)
    print(
        f"Electric agents with event mileage: {len(agent_metres):,}",
        file=sys.stderr,
    )
    print(f"Agents without an FSA match: {unmatched:,}", file=sys.stderr)
    print(f"'left link' events with unknown link IDs: {missing:,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
