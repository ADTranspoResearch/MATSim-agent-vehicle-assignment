#!/usr/bin/env python3
"""Export manuscript-ready FSA and citywide scenario result tables."""

from __future__ import annotations

import csv
import gzip
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = SCRIPT_DIR / "results"

FSA_FILE = PROJECT_ROOT / "data" / "FSA" / "agent_id_fsa_table.csv"
FSA_SHAPEFILE = PROJECT_ROOT / "data" / "FSA" / "quebec_fsa" / "quebec_fsa.shp"
EVENTS_FILE = PROJECT_ROOT / "data" / "MATSim" / "events" / "output_events.xml.gz"
NETWORK_FILE = PROJECT_ROOT / "data" / "MATSim" / "network" / "network_0409.xml"

SAMPLE_EXPANSION_FACTOR = 10
DAYS_PER_YEAR = 365

SCENARIOS = [
    ("2020", "REF", "REF2020", PROJECT_ROOT / "output" / "vehicles_updated_2020_REF.xml"),
    ("2035", "BAU", "BAU", PROJECT_ROOT / "output" / "vehicles_updated_2035_BAU.xml"),
    (
        "2035",
        "ACCELERATED_ADOPTION",
        "ACCEL",
        PROJECT_ROOT / "output" / "vehicles_updated_2035_ACCELERATED_ADOPTION.xml",
    ),
    (
        "2035",
        "DELAYED_ADOPTION",
        "DELAYED",
        PROJECT_ROOT / "output" / "vehicles_updated_2035_DELAYED_ADOPTION.xml",
    ),
    (
        "2035",
        "POLICY_ALIGNED",
        "POLICY",
        PROJECT_ROOT / "output" / "vehicles_updated_2035_POLICY_ALIGNED.xml",
    ),
]

COUNT_COLUMNS = {
    "ice_sedan": "veh_ice_sedan",
    "ice_suv": "veh_ice_suv",
    "hev_sedan": "veh_hev_sedan",
    "hev_suv": "veh_hev_suv",
    "electric": "veh_ev",
    "truck": "veh_ice_pickup_van",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def read_fsa_by_agent() -> dict[str, str]:
    df = pd.read_csv(FSA_FILE, encoding="utf-8-sig")
    fsa_col = "fsa" if "fsa" in df.columns else "CFSAUID"
    agent_col = "agent_id" if "agent_id" in df.columns else df.columns[0]
    return {
        str(row[agent_col]).strip(): str(row[fsa_col]).strip().upper()
        for _, row in df.iterrows()
        if str(row[agent_col]).strip()
    }


def read_population_by_fsa(fsa_by_agent: dict[str, str]) -> dict[str, int]:
    counts = Counter(fsa_by_agent.values())
    return {fsa: count * SAMPLE_EXPANSION_FACTOR for fsa, count in counts.items()}


def read_area_by_fsa() -> dict[str, float]:
    gdf = gpd.read_file(FSA_SHAPEFILE)
    if gdf.crs is None:
        raise ValueError(f"{FSA_SHAPEFILE} has no CRS; cannot compute km2 safely.")
    projected = gdf.to_crs("EPSG:3347")
    return {
        str(row["CFSAUID"]).upper(): float(row.geometry.area) / 1_000_000
        for _, row in projected.iterrows()
    }


def read_link_lengths() -> dict[str, float]:
    lengths: dict[str, float] = {}
    for _, elem in ET.iterparse(NETWORK_FILE, events=("end",)):
        if local_name(elem.tag) == "link":
            link_id = elem.get("id")
            length = elem.get("length")
            if link_id and length:
                lengths[link_id] = float(length)
        elem.clear()
    return lengths


def read_vehicle_counts(path: Path, fsa_by_agent: dict[str, str]) -> dict[str, Counter]:
    rows: dict[str, Counter] = defaultdict(Counter)
    for _, elem in ET.iterparse(path, events=("end",)):
        if local_name(elem.tag) == "vehicle":
            vehicle_id = elem.get("id") or ""
            vehicle_type = elem.get("type") or ""
            if vehicle_type in COUNT_COLUMNS and not vehicle_id.endswith("_car_passenger"):
                fsa = fsa_by_agent.get(vehicle_id, "UNKNOWN")
                rows[fsa][vehicle_type] += SAMPLE_EXPANSION_FACTOR
        elem.clear()
    return rows


def summarize_mobility(
    vehicle_ids: set[str],
    fsa_by_agent: dict[str, str],
    link_lengths: dict[str, float],
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    by_fsa: dict[str, dict[str, float]] = defaultdict(
        lambda: {"n_car_trips": 0, "vkt_total_km_day": 0.0}
    )
    agent_by_vehicle: dict[str, str] = {}

    with open_text(EVENTS_FILE) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if local_name(elem.tag) != "event":
                elem.clear()
                continue

            event_type = elem.get("type") or ""
            if event_type == "PersonEntersVehicle":
                person = elem.get("person")
                vehicle = elem.get("vehicle")
                if person and vehicle:
                    agent_by_vehicle[vehicle] = person
            elif event_type == "departure" and elem.get("legMode") == "car":
                person = elem.get("person")
                if person:
                    fsa = fsa_by_agent.get(person, "UNKNOWN")
                    by_fsa[fsa]["n_car_trips"] += SAMPLE_EXPANSION_FACTOR
            elif event_type == "left link":
                vehicle = elem.get("vehicle") or ""
                if vehicle in vehicle_ids:
                    agent = agent_by_vehicle.get(vehicle, vehicle)
                    fsa = fsa_by_agent.get(agent, "UNKNOWN")
                    km = link_lengths.get(elem.get("link") or "", 0.0) / 1000
                    by_fsa[fsa]["vkt_total_km_day"] += km * SAMPLE_EXPANSION_FACTOR
            elem.clear()

    total_agents = len(vehicle_ids) * SAMPLE_EXPANSION_FACTOR
    total_trips = sum(row["n_car_trips"] for row in by_fsa.values())
    total_vkt_km_day = sum(row["vkt_total_km_day"] for row in by_fsa.values())
    citywide = {
        "total_automobile_agents": total_agents,
        "total_daily_car_trips": total_trips,
        "total_vkt_Mkm_yr": total_vkt_km_day * DAYS_PER_YEAR / 1_000_000,
        "mean_daily_distance_per_auto_agent_km": total_vkt_km_day / total_agents
        if total_agents
        else 0.0,
    }
    return by_fsa, citywide


def read_metric_csv(path: Path, value_col: str) -> dict[str, float]:
    df = pd.read_csv(path)
    df = df[df["fsa"].astype(str).str.upper() != "UNKNOWN"].copy()
    df["fsa"] = df["fsa"].astype(str).str.upper()
    return dict(zip(df["fsa"], df[value_col].astype(float)))


def write_outputs() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    fsa_by_agent = read_fsa_by_agent()
    population = read_population_by_fsa(fsa_by_agent)
    area = read_area_by_fsa()

    vehicle_ids = set()
    for _, elem in ET.iterparse(SCENARIOS[0][3], events=("end",)):
        if local_name(elem.tag) == "vehicle":
            vehicle_id = elem.get("id") or ""
            vehicle_type = elem.get("type") or ""
            if vehicle_type in COUNT_COLUMNS and not vehicle_id.endswith("_car_passenger"):
                vehicle_ids.add(vehicle_id)
        elem.clear()

    mobility_by_fsa, citywide = summarize_mobility(
        vehicle_ids, fsa_by_agent, read_link_lengths()
    )

    all_fsas = set(fsa for fsa, value in population.items() if value > 0)

    output_rows = []
    for year, source_scenario, output_scenario, vehicle_file in SCENARIOS:
        vehicle_counts = read_vehicle_counts(vehicle_file, fsa_by_agent)
        co2 = read_metric_csv(
            RESULTS_DIR / f"co2_emissions_by_fsa_{year}_{source_scenario}.csv",
            "co2_kt_per_year",
        )
        electricity = read_metric_csv(
            RESULTS_DIR / f"ev_electricity_by_fsa_{year}_{source_scenario}.csv",
            "electricity_gwh_per_year",
        )
        ev_vkt = read_metric_csv(
            RESULTS_DIR / f"ev_electricity_by_fsa_{year}_{source_scenario}.csv",
            "distance_km_per_day_sample",
        )
        all_fsas.update(vehicle_counts)
        all_fsas.update(co2)
        all_fsas.update(electricity)
        all_fsas.discard("UNKNOWN")

        for fsa in sorted(all_fsas):
            counts = vehicle_counts.get(fsa, Counter())
            mobility = mobility_by_fsa.get(fsa, {})
            vkt_total_mkm_yr = (
                mobility.get("vkt_total_km_day", 0.0) * DAYS_PER_YEAR / 1_000_000
            )
            output_rows.append(
                {
                    "fsa": fsa,
                    "scenario": output_scenario,
                    "population": population.get(fsa, 0),
                    "area_km2": area.get(fsa, 0.0),
                    "n_vehicles": sum(counts.values()),
                    "n_ev": counts.get("electric", 0),
                    "veh_ice_sedan": counts.get("ice_sedan", 0),
                    "veh_ice_suv": counts.get("ice_suv", 0),
                    "veh_hev_sedan": counts.get("hev_sedan", 0),
                    "veh_hev_suv": counts.get("hev_suv", 0),
                    "veh_ev": counts.get("electric", 0),
                    "veh_ice_pickup_van": counts.get("truck", 0),
                    "co2_kt_yr": co2.get(fsa, 0.0),
                    "vkt_total_Mkm_yr": vkt_total_mkm_yr,
                    "vkt_ev_Mkm_yr": ev_vkt.get(fsa, 0.0)
                    * SAMPLE_EXPANSION_FACTOR
                    * DAYS_PER_YEAR
                    / 1_000_000,
                    "ev_electricity_GWh_yr": electricity.get(fsa, 0.0),
                    "n_agents": population.get(fsa, 0),
                    "n_car_trips": mobility.get("n_car_trips", 0),
                }
            )

    fsa_output = RESULTS_DIR / "fsa_results.csv"
    columns = [
        "fsa",
        "scenario",
        "population",
        "area_km2",
        "n_vehicles",
        "n_ev",
        "veh_ice_sedan",
        "veh_ice_suv",
        "veh_hev_sedan",
        "veh_hev_suv",
        "veh_ev",
        "veh_ice_pickup_van",
        "co2_kt_yr",
        "vkt_total_Mkm_yr",
        "vkt_ev_Mkm_yr",
        "ev_electricity_GWh_yr",
        "n_agents",
        "n_car_trips",
    ]
    pd.DataFrame(output_rows, columns=columns).to_csv(fsa_output, index=False, float_format="%.9f")

    scalar_output = RESULTS_DIR / "citywide_scalars.csv"
    with scalar_output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["metric", "value", "units"])
        writer.writerow(["total_automobile_agents", int(citywide["total_automobile_agents"]), "persons"])
        writer.writerow(["total_daily_car_trips", int(citywide["total_daily_car_trips"]), "trips/day"])
        writer.writerow(["total_vkt", f"{citywide['total_vkt_Mkm_yr']:.9f}", "million km/yr"])
        writer.writerow([
            "mean_daily_distance_per_auto_agent",
            f"{citywide['mean_daily_distance_per_auto_agent_km']:.9f}",
            "km",
        ])

    print(f"Wrote {fsa_output}")
    print(f"Wrote {scalar_output}")


if __name__ == "__main__":
    write_outputs()
