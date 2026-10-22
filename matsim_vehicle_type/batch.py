"""Resumable, daily FSA experiments using the real offline emissions module.

Nothing executes on import. The command-line entry point is
``scripts/run_scenario_batch.py``. All generated inputs and outputs stay inside
the chosen batch directory; GUI settings and production share files are untouched.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import xml.parsers.expat
from collections import Counter, defaultdict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from matsim_vehicle_type.config import PC_QC, SCN_CONFIGS
from matsim_vehicle_type.fleet import composition, growth
from matsim_vehicle_type.fleet.main import project_fleet_controls
from platform_gui import core


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("2020_REF", "2035_bau", "2035_acc_adopt", "2035_del_adopt", "2035_pol_align")
CATEGORIES = ("electric", "hev_sedan", "hev_suv", "ice_sedan", "ice_suv", "ice_van/pickup")
FSA_PATTERN = re.compile(r"^[A-Z][0-9][A-Z]$")
METRICS = (
    "vehicle_count", "ev_count", "active_ev_count", "total_co2_kg_per_day",
    "co2_kg_per_ev_per_day", "total_electricity_kwh_per_day", "electricity_kwh_per_ev_per_day",
)
SCHEMA_VERSION = 1


@dataclass
class BatchOptions:
    events: Path = ROOT / "data/MATSim/events/output_events_100.xml.gz"
    vehicles: Path = ROOT / "data/MATSim/vehicles/output_allVehicles_with_events_100_ids.xml.gz"
    network: Path = ROOT / "data/MATSim/network/network_0409.xml"
    fsa_lookup: Path = ROOT / "data/FSA/agent_id_fsa_table.csv"
    fsa_shapes: Path = ROOT / "data/FSA/quebec_fsa/quebec_fsa.shp"
    ownership_dir: Path = ROOT / "data/vehicles/ownership/personal_ownership"
    population_dir: Path = ROOT / "data/population/fsa_projected_pop"
    reference_shares: Path = ROOT / "data/vehicles/fsa_vehicle_share_2020.parquet"
    bev_shares: Path = ROOT / "data_post-processing/results/battery_electric_vehicle_type_share_quebec.csv"
    emission_module: Path = ROOT / "matsim-emissions"
    output_dir: Path = ROOT / "output/batch_100"
    scenarios: tuple[str, ...] = SCENARIOS
    seeds: tuple[int, ...] = (1, 2, 3, 4, 5)
    coordinates_crs: str = "EPSG:32187"
    resume: bool = True
    keep_emission_events: bool = False
    java_heap: str = "4g"
    chunksize: int = 300_000
    stage: str = "all"

    @property
    def template(self):
        return self.emission_module / "QC_input_data/config/config_average.xml"

    @property
    def factor_dir(self):
        return self.emission_module / "QC_input_data/emission_factor_table"


def log(message: str) -> None:
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}", flush=True)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp" + path.suffix)
    if path.suffix == ".parquet":
        frame.to_parquet(temporary, index=False)
    else:
        frame.to_csv(temporary, index=False, float_format="%.12g")
    temporary.replace(path)


def identity(path: Path) -> dict[str, Any]:
    """Hash small inputs/artifacts; identify large dumps by size and mtime."""
    stat = path.stat()
    value = {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if stat.st_size <= 64 * 1024 * 1024:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        value["sha256"] = digest.hexdigest()
    return value


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def save_stage(path: Path, key: str, outputs: list[Path], **details) -> None:
    write_json(path, {"fingerprint": key, "outputs": [identity(p) for p in outputs], **details})


def completed_stage(path: Path, key: str, resume: bool = True) -> dict[str, Any] | None:
    if not resume or not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["fingerprint"] != key:
            return None
        for artifact in state["outputs"]:
            if identity(Path(artifact["path"])) != artifact:
                return None
        return state
    except (OSError, ValueError, KeyError):
        return None


def valid_fsa(value: Any) -> bool:
    return bool(FSA_PATTERN.fullmatch(str(value).strip().upper()))


def read_vehicle_inventory(path: Path) -> tuple[list[str], set[str]]:
    """Use type, rather than network-mode events, to identify buses."""
    personal, buses, seen = [], set(), set()
    with core.open_text(path) as stream:
        context = ET.iterparse(stream, events=("start", "end"))
        _, root = next(context)
        for event, element in context:
            if event == "end" and element.tag.rsplit("}", 1)[-1] == "vehicle":
                vehicle = element.get("id")
                if not vehicle or vehicle in seen:
                    raise ValueError(f"Missing or duplicate vehicle ID: {vehicle!r}")
                seen.add(vehicle)
                if (element.get("type") or "").lower() == "bus":
                    buses.add(vehicle)
                else:
                    personal.append(vehicle)
                root.clear()
    if not personal:
        raise ValueError("The vehicle input contains no non-bus vehicles.")
    return sorted(personal), buses


def scan_xml(path: Path, handler: Callable[[dict[str, str]], None]) -> int:
    """SAX-style parsing keeps memory independent of the event-file length."""
    parser = xml.parsers.expat.ParserCreate()
    count = 0
    last = time.monotonic()

    def start(tag, attributes):
        nonlocal count
        if tag == "event":
            count += 1
            handler(attributes)

    parser.StartElementHandler = start
    with path.open("rb") as raw:
        stream = gzip.GzipFile(fileobj=raw) if path.suffix == ".gz" else raw
        try:
            while True:
                chunk = stream.read(4 * 1024 * 1024)
                if not chunk:
                    break
                parser.Parse(chunk, False)
                if time.monotonic() - last >= 30:
                    log(f"{path.name}: {count:,} events; {100 * raw.tell() / max(path.stat().st_size, 1):.1f}% input")
                    last = time.monotonic()
            parser.Parse(b"", True)
        finally:
            if stream is not raw:
                stream.close()
    return count


def scan_mobility(events: Path, personal: set[str], buses: set[str], lengths: dict[str, float]):
    homes, drivers, metres = {}, {}, defaultdict(float)
    diagnostics = Counter()
    missing_links, unknown_vehicles = Counter(), Counter()

    def handle(event):
        kind = event.get("type")
        if kind in ("actstart", "actend") and event.get("actType") == "home":
            person = event.get("person")
            if person and event.get("x") is not None and event.get("y") is not None:
                xy = (float(event["x"]), float(event["y"]))
                if not all(math.isfinite(v) for v in xy):
                    raise ValueError(f"Non-finite home coordinates: {person}")
                if person in homes and homes[person] != xy:
                    diagnostics["conflicting_home_events"] += 1
                homes.setdefault(person, xy)
        elif kind == "vehicle enters traffic":
            vehicle, person = event.get("vehicle"), event.get("person")
            if vehicle in personal and person:
                if vehicle in drivers and drivers[vehicle] != person:
                    raise ValueError(f"Vehicle {vehicle} has multiple drivers; home attribution is ambiguous.")
                drivers[vehicle] = person
            elif vehicle and vehicle not in buses and vehicle not in personal:
                unknown_vehicles[vehicle] += 1
        elif kind == "left link":
            vehicle, link = event.get("vehicle"), event.get("link")
            if link not in lengths:
                missing_links[link or "(missing)"] += 1
            elif vehicle in personal:
                metres[vehicle] += lengths[link]
            if vehicle and vehicle not in personal and vehicle not in buses:
                unknown_vehicles[vehicle] += 1

    count = scan_xml(events, handle)
    diagnostics.update({"events": count, "home_persons": len(homes), "active_non_bus_vehicles": len(metres)})
    diagnostics["missing_link_events"] = sum(missing_links.values())
    diagnostics["unknown_vehicle_events"] = sum(unknown_vehicles.values())
    if missing_links or unknown_vehicles:
        raise ValueError(f"Events incompatible with network/vehicles: missing links {missing_links.most_common(10)}; "
                         f"unknown vehicles {unknown_vehicles.most_common(10)}")
    return homes, drivers, dict(metres), dict(diagnostics)


def locate_homes(homes: dict[str, tuple[float, float]], shapes_path: Path, crs: str):
    import geopandas as gpd

    points = pd.DataFrame([(person, *xy) for person, xy in homes.items()], columns=["agent_id", "x", "y"])
    if points.empty:
        return {}, {"spatial_unmatched_persons": 0, "boundary_ambiguous_persons": 0}
    points = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(points.x, points.y), crs=crs)
    shapes = gpd.read_file(shapes_path)
    if shapes.crs is None or "CFSAUID" not in shapes:
        raise ValueError("FSA shapefile must have a CRS and CFSAUID column.")
    shapes = shapes.to_crs(crs)
    joined = gpd.sjoin(points, shapes[["CFSAUID", "geometry"]], how="left", predicate="intersects")
    matched = joined.loc[joined.CFSAUID.notna()].sort_values(["agent_id", "CFSAUID"])
    ambiguous = int((matched.groupby("agent_id").CFSAUID.nunique() > 1).sum())
    # Shared polygon boundaries get a stable choice, independent of file order.
    matched = matched.drop_duplicates("agent_id")
    result = {str(r.agent_id): str(r.CFSAUID).strip().upper() for r in matched.itertuples()}
    return result, {"spatial_unmatched_persons": len(homes) - len(result), "boundary_ambiguous_persons": ambiguous}


def prepare_mobility(options: BatchOptions, cache: Path, key: str, ev_module):
    marker, output = cache / "mobility.done.json", cache / "vehicles.parquet"
    personal, buses = read_vehicle_inventory(options.vehicles)
    if completed_stage(marker, key, options.resume):
        log("Reusing validated mobility cache")
        return pd.read_parquet(output), buses
    log("Scanning 100% events once for homes, drivers and vehicle distances")
    lengths = ev_module.read_link_lengths(options.network)
    if not lengths or any(not math.isfinite(v) or v < 0 for v in lengths.values()):
        raise ValueError("Network link lengths must be finite, nonnegative, and nonempty.")
    homes, drivers, metres, diagnostics = scan_mobility(options.events, set(personal), buses, lengths)
    home_fsa, spatial_diagnostics = locate_homes(homes, options.fsa_shapes, options.coordinates_crs)
    lookup = core.read_fsa_lookup(options.fsa_lookup)
    diagnostics.update(spatial_diagnostics)
    records = []
    for vehicle in personal:
        agent = drivers.get(vehicle, vehicle)
        fsa, source = home_fsa.get(agent), "event_home"
        if not valid_fsa(fsa):
            fsa, source = lookup.get(agent), "existing_lookup"
        if not valid_fsa(fsa):
            fsa, source = "UNKNOWN", "unmatched"
        records.append((vehicle, agent, fsa, source, metres.get(vehicle, 0.0)))
    frame = pd.DataFrame(records, columns=["vehicle_id", "agent_id", "fsa", "fsa_source", "distance_metres_per_day"])
    diagnostics["non_bus_vehicles"] = len(frame)
    diagnostics["bus_vehicles"] = len(buses)
    diagnostics["vehicle_fsa_sources"] = {str(k): int(v) for k, v in frame.fsa_source.value_counts().items()}
    diagnostics["lookup_disagreements"] = sum(
        valid_fsa(lookup.get(agent)) and lookup[agent] != fsa for agent, fsa in home_fsa.items()
    )
    write_frame(output, frame)
    homes_output = cache / "home_fsa_lookup.parquet"
    write_frame(homes_output, pd.DataFrame(sorted(home_fsa.items()), columns=["agent_id", "fsa"]))
    unmatched_output = cache / "unmatched_vehicles.csv"
    write_frame(unmatched_output, frame.loc[frame.fsa == "UNKNOWN"])
    diagnostic_output = cache / "mobility_diagnostics.json"
    write_json(diagnostic_output, diagnostics)
    save_stage(marker, key, [output, homes_output, unmatched_output, diagnostic_output])
    return frame, buses


def aggregate_history(options: BatchOptions, fsas: set[str], cache: Path, key: str):
    counts_path, totals_path = cache / "historical_counts.parquet", cache / "historical_raw_totals.parquet"
    marker = cache / "history.done.json"
    if completed_stage(marker, key, options.resume):
        return pd.read_parquet(counts_path), pd.read_parquet(totals_path)
    records, totals = [], []
    for year in range(2013, 2021):
        path = options.ownership_dir / f"Personal_McGill_SAAQ_{year}_2024-01-10.csv"
        log(f"Aggregating {year} SAAQ history by FSA")
        fleet, entrants, raw_size, raw_new, raw_exit = (Counter() for _ in range(5))
        for chunk in pd.read_csv(path, usecols=["AnneeSAAQ", "RTA", "Entrant", "Sortant", "vehicle_type"],
                                 dtype={"RTA": "string", "vehicle_type": "string"}, chunksize=options.chunksize):
            chunk["RTA"] = chunk.RTA.str.strip().str.upper()
            chunk = chunk.loc[chunk.RTA.isin(fsas)]
            if chunk.empty:
                continue
            if not chunk.AnneeSAAQ.eq(year).all():
                raise ValueError(f"Registration year mismatch in {path}")
            for subset, counter in ((chunk, raw_size), (chunk.loc[chunk.Entrant.eq(1)], raw_new),
                                    (chunk.loc[chunk.Sortant.eq(1)], raw_exit)):
                counter.update(subset.groupby("RTA").size().to_dict())
            # Same eligible types as composition.historic_fleet_composition;
            # fleet-size controls deliberately retain all raw personal records.
            eligible = chunk.loc[~chunk.vehicle_type.isin(["unknown", "other", "hev_van/pickup"])]
            for subset, counter in ((eligible, fleet), (eligible.loc[eligible.Entrant.eq(1)], entrants)):
                counter.update(subset.groupby(["RTA", "vehicle_type"]).size().to_dict())
        for (fsa, kind), count in sorted(fleet.items()):
            records.append((fsa, year, kind, count, entrants[fsa, kind]))
        for fsa, size in sorted(raw_size.items()):
            totals.append((fsa, year, size, raw_new[fsa], raw_exit[fsa]))
    counts = pd.DataFrame(records, columns=["fsa", "year", "vehicle_type", "fleet_count", "entrant_count"])
    raw = pd.DataFrame(totals, columns=["fsa", "year", "size", "new", "exit"])
    write_frame(counts_path, counts)
    write_frame(totals_path, raw)
    save_stage(marker, key, [counts_path, totals_path])
    return counts, raw


def checked_shares(values: dict[str, float]) -> dict[str, float]:
    unknown = set(values) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"Unsupported predicted vehicle types: {sorted(unknown)}")
    array = np.array([float(values.get(kind, 0.0)) for kind in CATEGORIES])
    if not np.isfinite(array).all() or (array < 0).any() or array.sum() <= 0:
        raise ValueError("Vehicle shares must be finite, nonnegative, and have positive total mass.")
    array /= array.sum()
    return dict(zip(CATEGORIES, map(float, array)))


def build_distributions(options: BatchOptions, base: pd.DataFrame, cache: Path, key: str):
    output, marker = cache / "distributions.json", cache / "distributions.done.json"
    if completed_stage(marker, key, options.resume):
        return json.loads(output.read_text(encoding="utf-8"))
    fsas = set(PC_QC) | {f for f in base.fsa.unique() if valid_fsa(f)}
    counts, raw_totals = aggregate_history(options, fsas, cache, key)
    reference = core.read_vehicle_distribution(options.reference_shares)
    result = {label: {"shares": {}, "fleet_sizes": {}, "fallback_reasons": {}} for label in SCENARIOS}
    diagnostics = []
    for fsa in sorted(fsas):
        history = counts.loc[counts.fsa.eq(fsa)]
        ref_size = float(history.loc[history.year.eq(2020), "fleet_count"].sum())
        if fsa in reference:
            try:
                result["2020_REF"]["shares"][fsa] = checked_shares(dict(reference[fsa]))
                result["2020_REF"]["fleet_sizes"][fsa] = ref_size
            except ValueError as error:
                result["2020_REF"]["fallback_reasons"][fsa] = str(error)
        else:
            result["2020_REF"]["fallback_reasons"][fsa] = "No 2020 historical share row"
        try:
            if set(history.year.unique()) != set(range(2013, 2021)):
                raise ValueError("Incomplete 2013-2020 fleet history")
            historic_frames = [group[["year", "vehicle_type", "fleet_count"]].rename(
                columns={"year": "AnneeSAAQ", "fleet_count": "count"})
                for _, group in history.groupby("year", sort=True)]
            entrant_2020 = history.loc[history.year.eq(2020) & history.entrant_count.gt(0)].set_index("vehicle_type").entrant_count
            initial = (entrant_2020 / entrant_2020.sum()).to_dict()
            trends = composition.get_growth_trends(historic_frames)
            if "electric" not in initial or not all(math.isfinite(trends[t]) for t in initial):
                raise ValueError("EV initial share or finite growth rates unavailable")
            population_path = options.population_dir / f"{fsa}_projected_pop.csv"
            population = pd.read_csv(population_path, thousands=",").set_index("year")
            if population.index.has_duplicates or not np.isfinite(population.persons).all() or population.persons.le(0).any():
                raise ValueError("Invalid or duplicate population observations")
            fleet_size = raw_totals.loc[raw_totals.fsa.eq(fsa)].drop(columns="fsa")
            controls = project_fleet_controls(fleet_size, population)
            if not set(range(2021, 2041)).issubset(controls.index):
                raise ValueError("Population controls do not cover 2021-2040")
            if not np.isfinite(controls.loc[2021:2040, ["new", "implied_exit"]]).all().all():
                raise ValueError("Non-finite fleet controls")
        except (ValueError, KeyError, OSError, ZeroDivisionError) as error:
            for label in SCENARIOS[1:]:
                result[label]["fallback_reasons"][fsa] = str(error)
            diagnostics.append({"fsa": fsa, "scenario": "all_future", "reason": str(error)})
            continue
        for label in SCENARIOS[1:]:
            scenario = label.removeprefix("2035_")
            try:
                new_mix = composition.predict_composition_trend(initial, trends, start_year=2021, end_year=2041, scenario=scenario)
                if not np.isfinite(new_mix.to_numpy()).all() or new_mix.lt(0).any().any():
                    raise ValueError("Invalid new-vehicle composition")
                np.testing.assert_allclose(new_mix.sum(axis=0), 1.0, atol=1e-9)
                stock = growth.predict_fleet_over_time(historic_frames, controls, new_mix, fsa, write_outputs=False, scenario=scenario)
                target = stock[2035]
                shares = checked_shares(target.to_dict())
                result[label]["shares"][fsa] = shares
                result[label]["fleet_sizes"][fsa] = float(target.sum())
            except (ValueError, KeyError, ZeroDivisionError, OverflowError, AssertionError) as error:
                result[label]["fallback_reasons"][fsa] = str(error)
                diagnostics.append({"fsa": fsa, "scenario": scenario, "reason": str(error)})
    for label, distribution in result.items():
        city_fsas = [f for f in sorted(PC_QC) if f in distribution["shares"] and distribution["fleet_sizes"].get(f, 0) > 0]
        total = sum(distribution["fleet_sizes"][f] for f in city_fsas)
        if total <= 0:
            raise ValueError(f"No valid city fleets available to construct the {label} fallback")
        distribution["city_average"] = checked_shares({kind: sum(distribution["shares"][f][kind] * distribution["fleet_sizes"][f]
                                                                  for f in city_fsas) / total for kind in CATEGORIES})
        distribution["city_average_fsas"] = city_fsas
        distribution["city_average_fleet_size"] = total
    write_json(output, result)
    diagnostics_path = cache / "prediction_diagnostics.json"
    write_json(diagnostics_path, {"forecast_years": [2021, 2040], "scenario_settings": SCN_CONFIGS, "fallbacks": diagnostics})
    save_stage(marker, key, [output, diagnostics_path])
    return result


def assign_frame(base: pd.DataFrame, distribution: dict, year: int, scenario: str, seed: int, body_shares: dict, ev_module):
    """One draw per sorted non-bus vehicle provides paired scenario replicates."""
    rng = random.Random(seed)
    records = []
    for row in base.sort_values("vehicle_id").itertuples(index=False):
        local = distribution["shares"].get(row.fsa)
        reason = "local" if local is not None else ("unknown_fsa" if row.fsa == "UNKNOWN" else "missing_fsa_distribution")
        shares = local if local is not None else distribution["city_average"]
        kind = rng.choices(CATEGORIES, weights=[shares[k] for k in CATEGORIES], k=1)[0]
        xml_kind = core.VEHICLE_TYPE_ALIAS.get(kind, kind)
        body, rate = "", 0.0
        if kind == "electric":
            body = ev_module.assign_vehicle_type(row.agent_id, scenario, body_shares)
            rate = ev_module.KWH_PER_KM_BY_TYPE[body]
        records.append((row.vehicle_id, row.agent_id, row.fsa, row.fsa_source, xml_kind, reason,
                        body, rate, row.distance_metres_per_day / 1000,
                        row.distance_metres_per_day / 1000 * rate))
    return pd.DataFrame(records, columns=["vehicle_id", "agent_id", "fsa", "fsa_source", "vehicle_type",
        "distribution_source", "bev_body_type", "kwh_per_km", "distance_km_per_day", "electricity_kwh_per_day"])


def write_assigned_vehicles(source: Path, target: Path, assigned: pd.DataFrame) -> None:
    with core.open_text(source) as stream:
        tree = ET.parse(stream)
    root = tree.getroot()
    namespace = root.tag.rsplit("}", 1)[0] + "}" if "}" in root.tag else ""
    definitions = ET.fromstring(core.VEHICLE_TYPE_XML)
    templates = {node.get("id"): node for node in definitions}
    # Convert helper templates to the actual root namespace, including fixtures.
    for template in templates.values():
        for node in template.iter():
            node.tag = namespace + node.tag.rsplit("}", 1)[-1]
    for node in list(root):
        if node.tag.rsplit("}", 1)[-1] != "vehicleType":
            continue
        kind = node.get("id")
        if kind == "Bus":
            # Keep capacities and transit metadata; supply only HBEFA metadata.
            for engine in list(node):
                if engine.tag.rsplit("}", 1)[-1] == "engineInformation":
                    node.remove(engine)
            node.append(deepcopy(templates["Bus"].find(namespace + "engineInformation")))
        elif kind in templates:
            root.remove(node)
    insert_at = next((i for i, node in enumerate(root) if node.tag.rsplit("}", 1)[-1] == "vehicle"), len(root))
    for kind, template in templates.items():
        if kind != "Bus":
            root.insert(insert_at, deepcopy(template))
            insert_at += 1
    kinds = dict(zip(assigned.vehicle_id, assigned.vehicle_type))
    seen = set()
    for node in root:
        if node.tag.rsplit("}", 1)[-1] == "vehicle" and node.get("id") in kinds:
            vehicle = node.get("id")
            node.set("type", kinds[vehicle])
            seen.add(vehicle)
    if seen != set(kinds):
        raise ValueError("Assigned vehicle IDs do not match the input vehicle inventory")
    ET.register_namespace("", "http://www.matsim.org/files/dtd")
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream:
            tree.write(stream, encoding="utf-8", xml_declaration=True)
    temporary.replace(target)


def summarize_emissions(path: Path, personal: set[str], buses: set[str]):
    grams = defaultdict(float)
    counts = Counter()

    def handle(event):
        kind = event.get("type")
        if kind not in ("warmEmissionEvent", "coldEmissionEvent"):
            return
        vehicle = event.get("vehicleId") or event.get("vehicle")
        if vehicle in buses:
            counts["excluded_bus_events"] += 1
            return
        if vehicle not in personal:
            raise ValueError(f"Emission event contains unknown vehicle {vehicle!r}")
        if "CO2" not in event:
            raise ValueError(f"CO2 missing from {kind} for {vehicle}")
        value = float(event["CO2"])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid CO2 value for vehicle {vehicle}: {value}")
        grams[vehicle] += value
        counts[kind] += 1

    scan_xml(path, handle)
    return dict(grams), dict(counts)


def daily_fsa_results(assigned: pd.DataFrame, grams: dict[str, float], fsas: list[str], year: int, scenario: str, seed: int):
    audit = assigned.copy()
    audit["co2_kg_per_day"] = audit.vehicle_id.map(grams).fillna(0) / 1000.0
    audit["ev_count"] = audit.vehicle_type.eq("electric").astype(int)
    audit["active_ev_count"] = (audit.vehicle_type.eq("electric") & audit.distance_km_per_day.gt(0)).astype(int)
    result = audit.groupby("fsa").agg(vehicle_count=("vehicle_id", "size"), ev_count=("ev_count", "sum"),
        active_ev_count=("active_ev_count", "sum"), total_co2_kg_per_day=("co2_kg_per_day", "sum"),
        total_electricity_kwh_per_day=("electricity_kwh_per_day", "sum")).reindex(fsas, fill_value=0)
    denominator = result.ev_count.replace(0, np.nan)
    result["co2_kg_per_ev_per_day"] = result.total_co2_kg_per_day / denominator
    result["electricity_kwh_per_ev_per_day"] = result.total_electricity_kwh_per_day / denominator
    result = result.reset_index(names="fsa")
    result.insert(0, "seed", seed)
    result.insert(0, "scenario", scenario)
    result.insert(0, "year", year)
    result = result[["year", "scenario", "seed", "fsa", *METRICS]]
    if int(result.vehicle_count.sum()) != len(audit) or int(result.ev_count.sum()) != int(audit.ev_count.sum()):
        raise ValueError("FSA vehicle-count conservation failed")
    for actual, expected in ((result.total_co2_kg_per_day.sum(), math.fsum(grams.values()) / 1000),
                             (result.total_electricity_kwh_per_day.sum(), math.fsum(audit.electricity_kwh_per_day))):
        if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError(f"FSA total conservation failed: {actual} != {expected}")
    return result, audit.drop(columns=["ev_count", "active_ev_count"])


def aggregate_replicates(combined: pd.DataFrame) -> pd.DataFrame:
    if combined.duplicated(["year", "scenario", "seed", "fsa"]).any():
        raise ValueError("Duplicate scenario/seed/FSA rows")
    groups = combined.groupby(["year", "scenario", "fsa"], sort=True)
    result = groups.seed.nunique().to_frame("seed_count")
    for metric in METRICS:
        result[f"{metric}_mean"] = groups[metric].mean()
        result[f"{metric}_std"] = groups[metric].std(ddof=1)
        result[f"{metric}_n_valid"] = groups[metric].count()
    return result.reset_index()


def write_emission_config(options: BatchOptions, run_dir: Path, assigned_path: Path, seed: int):
    tree = ET.parse(options.template)
    root = tree.getroot()
    params = {
        ("controller", "outputDirectory"): str(run_dir / "emission") + "/",
        ("network", "inputNetworkFile"): str(options.network),
        ("plans", "inputPlansFile"): "null",
        ("vehicles", "vehiclesFile"): str(assigned_path),
        ("global", "randomSeed"): str(seed),
        ("global", "numberOfThreads"): "1",
        ("eventsManager", "numberOfThreads"): "1",
        ("emissions", "averageFleetColdEmissionFactorsFile"): str(options.factor_dir / "hbefa_cold_emission_factor_table.csv"),
        ("emissions", "averageFleetWarmEmissionFactorsFile"): str(options.factor_dir / "warm_emission_factor_table0416.csv"),
    }
    for (module, name), value in params.items():
        core.set_config_param(root, module, name, value)
    path = run_dir / "emission_config.xml"
    core.write_matsim_config(tree, path)
    return path


def maven_command() -> str:
    command = next((shutil.which(p) for p in core.MAVEN_CANDIDATES if shutil.which(p)), None)
    if command is None:
        raise RuntimeError("Maven is required for the emission stage; install mvn or add it to PATH.")
    return command


def maven_environment(options: BatchOptions):
    env = os.environ.copy()
    env["MAVEN_OPTS"] = f"-Xmx{options.java_heap} -Dmatsim.preferLocalDtds=true " + env.get("MAVEN_OPTS", "")
    return env


def run_logged(command: list[str], options: BatchOptions, path: Path):
    log(f"Starting Maven; log: {path}")
    with path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(command) + "\n")
        stream.flush()
        process = subprocess.Popen(command, cwd=options.emission_module, env=maven_environment(options),
                                   stdout=stream, stderr=subprocess.STDOUT)
        try:
            while True:
                try:
                    code = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    log(f"Maven running; log size {path.stat().st_size / 1024 / 1024:.1f} MiB")
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if code:
        raise RuntimeError(f"Maven failed with exit code {code}; inspect {path}")


def input_manifest(options: BatchOptions):
    files = [options.events, options.vehicles, options.network, options.fsa_lookup, options.reference_shares,
             options.bev_shares, options.template, options.emission_module / "pom.xml",
             options.factor_dir / "warm_emission_factor_table0416.csv",
             options.factor_dir / "hbefa_cold_emission_factor_table.csv"]
    files.extend(options.fsa_shapes.with_suffix(suffix) for suffix in (".shp", ".shx", ".dbf", ".prj"))
    files.extend(options.ownership_dir / f"Personal_McGill_SAAQ_{year}_2024-01-10.csv" for year in range(2013, 2021))
    population_files = sorted(options.population_dir.glob("*_projected_pop.csv"))
    if not population_files:
        raise FileNotFoundError(f"No FSA population projections in {options.population_dir}")
    files.extend(population_files)
    files.extend(sorted((options.emission_module / "src/main/java").rglob("*.java")))
    files.extend([Path(__file__), ROOT / "scripts/run_scenario_batch.py", ROOT / "matsim_vehicle_type/config.py",
                  ROOT / "matsim_vehicle_type/fleet/composition.py", ROOT / "matsim_vehicle_type/fleet/growth.py",
                  ROOT / "matsim_vehicle_type/fleet/main.py", ROOT / "platform_gui/core.py",
                  ROOT / "data_post-processing/summarize_ev_electricity_by_scenario.py",
                  ROOT / "requirements-batch.txt"])
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing batch inputs:\n" + "\n".join(missing))
    return {"schema_version": SCHEMA_VERSION, "inputs": [identity(p) for p in files],
            "coordinate_crs": options.coordinates_crs, "sample_expansion_factor": 1,
            "time_basis": "simulated_day", "scenario_settings": SCN_CONFIGS,
            "forecast_start": 2021, "forecast_end_inclusive": 2040, "city_fsas": sorted(PC_QC),
            "python_version": sys.version,
            "libraries": {name: importlib.metadata.version(name) for name in
                          ("numpy", "pandas", "geopandas", "shapely", "pyarrow")}}


@contextmanager
def batch_lock(directory: Path):
    """Do not let two processes overwrite or clean up the same experiment."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".batch.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"Another process is using batch directory {directory}") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run_batch(options: BatchOptions) -> None:
    with batch_lock(options.output_dir):
        _run_batch(options)


def _run_batch(options: BatchOptions) -> None:
    options.output_dir.mkdir(parents=True, exist_ok=True)
    cache = options.output_dir / "cache"
    cache.mkdir(exist_ok=True)
    manifest = input_manifest(options)
    key = fingerprint(manifest)
    manifest_path = options.output_dir / "inputs.json"
    if manifest_path.exists() and fingerprint(json.loads(manifest_path.read_text(encoding="utf-8"))) != key:
        raise ValueError("Batch inputs/code changed. Use a fresh --output-dir to keep earlier experiments traceable.")
    write_json(manifest_path, manifest)
    ev_module = core.load_script_module("batch_ev_electricity", ROOT / "data_post-processing/summarize_ev_electricity_by_scenario.py")
    base, buses = prepare_mobility(options, cache, key, ev_module)
    distributions = build_distributions(options, base, cache, key)
    fsas = sorted(set(PC_QC) | set(base.fsa) | {"UNKNOWN"})
    if options.stage == "prepare":
        log("Preparation complete; no emission runs requested")
        return
    body_shares = {year: ev_module.read_historical_shares(options.bev_shares, 2020 if year == 2020 else 2024)
                   for year in (2020, 2035)}
    frames = []
    build_ready = False
    batch_status = {"fingerprint": key, "scenarios": list(options.scenarios), "seeds": list(options.seeds), "completed": []}
    status_path = options.output_dir / "batch_status.json"
    write_json(status_path, batch_status)
    try:
        for label in options.scenarios:
            year_text, scenario = label.split("_", 1)
            year = int(year_text)
            for seed in options.seeds:
                run_id = f"{label}/seed{seed}"
                run_dir = options.output_dir / label / f"seed{seed}"
                run_dir.mkdir(parents=True, exist_ok=True)
                run_key = fingerprint({"inputs": key, "scenario": label, "seed": seed})
                summary_marker = run_dir / "summary.done.json"
                table_path = run_dir / "fsa_results.csv"
                raw_events = run_dir / "emission/emission.events.offline.xml.gz"
                summary_state = completed_stage(summary_marker, run_key, options.resume)
                if summary_state and options.stage != "assign":
                    log(f"Reusing completed {run_id}")
                    frames.append(pd.read_csv(table_path, keep_default_na=True))
                    batch_status["completed"].append(run_id)
                    if not options.keep_emission_events and raw_events.exists():
                        raw_events.unlink()
                    continue
                log(f"Processing {run_id}")
                batch_status["current_run"] = run_id
                write_json(status_path, batch_status)
                assignment_path, assigned_path = run_dir / "assignments.parquet", run_dir / "vehicles.xml.gz"
                assignment_marker = run_dir / "assignment.done.json"
                reuse_dependencies = options.resume or options.stage == "summarize"
                if not completed_stage(assignment_marker, run_key, reuse_dependencies):
                    if options.stage == "summarize":
                        raise RuntimeError(f"{run_id}: assignment missing; run --stage all first")
                    assigned = assign_frame(base, distributions[label], year, scenario, seed, body_shares[year], ev_module)
                    write_assigned_vehicles(options.vehicles, assigned_path, assigned)
                    write_frame(assignment_path, assigned)
                    fallback_rows = assigned.loc[assigned.distribution_source.ne("local")]
                    fallback_counts = fallback_rows.groupby(["fsa", "distribution_source"]).size().reset_index(name="vehicle_count")
                    diagnostic_path = run_dir / "assignment_diagnostics.json"
                    write_json(diagnostic_path, {"seed": seed, "scenario": label, "assigned_count": len(assigned),
                        "bus_count": len(buses), "type_counts": {str(k): int(v) for k, v in assigned.vehicle_type.value_counts().items()},
                        "fallback_counts": fallback_counts.to_dict("records"),
                        "fallback_reasons": distributions[label]["fallback_reasons"]})
                    save_stage(assignment_marker, run_key, [assignment_path, assigned_path, diagnostic_path])
                if options.stage == "assign":
                    continue
                assigned = pd.read_parquet(assignment_path)
                emission_marker = run_dir / "emission.done.json"
                if not completed_stage(emission_marker, run_key, reuse_dependencies):
                    if options.stage == "summarize":
                        raise RuntimeError(f"{run_id}: emission events missing; run --stage all first")
                    build_marker = cache / "build.done.json"
                    if not build_ready:
                        if not completed_stage(build_marker, key, options.resume):
                            run_logged([maven_command(), "-q", "-DskipTests", "compile"], options, options.output_dir / "maven_build.log")
                            main_class = options.emission_module / "target/classes/org/matsim/contrib/emissions/example/RunAverageEmissionToolOfflineExample.class"
                            save_stage(build_marker, key, [main_class])
                        build_ready = True
                    config = write_emission_config(options, run_dir, assigned_path, seed)
                    raw_events.parent.mkdir(exist_ok=True)
                    if raw_events.exists():
                        # Only a failed/incomplete artifact inside this run directory.
                        raw_events.unlink()
                    run_logged([maven_command(), "-q", "exec:java", f"-Dexec.mainClass={core.AVERAGE_EMISSION_MAIN_CLASS}",
                                f"-Demission.events.input={options.events}", f"-Dexec.args={config}"], options, run_dir / "emission.log")
                    if not raw_events.is_file() or raw_events.stat().st_size == 0:
                        raise RuntimeError(f"{run_id}: emission module did not write {raw_events}")
                    save_stage(emission_marker, run_key, [raw_events, config])
                grams, emission_counts = summarize_emissions(raw_events, set(assigned.vehicle_id), buses)
                result, audit = daily_fsa_results(assigned, grams, fsas, year, scenario, seed)
                audit_path, diagnostics_path = run_dir / "vehicle_results.parquet", run_dir / "summary_diagnostics.json"
                write_frame(table_path, result)
                write_frame(audit_path, audit)
                write_json(diagnostics_path, {"emission_event_counts": emission_counts, "vehicle_count": len(audit),
                    "total_co2_kg_per_day": float(result.total_co2_kg_per_day.sum()),
                    "total_electricity_kwh_per_day": float(result.total_electricity_kwh_per_day.sum()),
                    "sample_expansion_factor": 1, "annualization": False, "conservation_checks_passed": True})
                save_stage(summary_marker, run_key, [table_path, audit_path, diagnostics_path, assignment_path,
                    assigned_path, run_dir / "assignment_diagnostics.json", run_dir / "emission_config.xml"],
                    raw_events_cleaned=not options.keep_emission_events)
                # The summary marker deliberately does not depend on the large dump.
                if not options.keep_emission_events:
                    raw_events.unlink()
                frames.append(result)
                batch_status["completed"].append(run_id)
                write_json(status_path, batch_status)
        if options.stage == "assign":
            batch_status["state"] = "assignments_complete"
        else:
            combined = pd.concat(frames, ignore_index=True)
            expected_runs = len(options.scenarios) * len(options.seeds)
            if len(batch_status["completed"]) != expected_runs:
                raise RuntimeError("Incomplete experiment matrix; refusing to publish a complete summary")
            stats = aggregate_replicates(combined)
            if not stats.seed_count.eq(len(options.seeds)).all():
                raise RuntimeError("FSA seed coverage is inconsistent")
            write_frame(options.output_dir / "fsa_results_all_seeds.csv", combined)
            write_frame(options.output_dir / "fsa_results_seed_statistics.csv", stats)
            city = combined.groupby(["year", "scenario", "seed"], as_index=False)[
                ["vehicle_count", "ev_count", "active_ev_count", "total_co2_kg_per_day", "total_electricity_kwh_per_day"]].sum()
            denominator = city.ev_count.replace(0, np.nan)
            city["co2_kg_per_ev_per_day"] = city.total_co2_kg_per_day / denominator
            city["electricity_kwh_per_ev_per_day"] = city.total_electricity_kwh_per_day / denominator
            write_frame(options.output_dir / "all_fsa_totals_by_seed.csv", city)
            batch_status["state"] = "complete"
        batch_status.pop("current_run", None)
        write_json(status_path, batch_status)
        log(f"Batch {batch_status['state']}; output: {options.output_dir}")
    except BaseException as error:
        batch_status.update(state="failed", error=f"{type(error).__name__}: {error}")
        write_json(status_path, batch_status)
        raise
