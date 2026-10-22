from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_DIR / "config.json"
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "default_config.json"
AVERAGE_EMISSION_MAIN_CLASS = (
    "org.matsim.contrib.emissions.example.RunAverageEmissionToolOfflineExample"
)
MATSIM_CONFIG_DOCTYPE = '<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">'
MAVEN_CANDIDATES = (
    "mvn",
    "/opt/homebrew/bin/mvn",
    "/usr/local/bin/mvn",
)
QUEBEC_CITY_FSA_FILE = PROJECT_ROOT / "data" / "FSA" / "fsa_codes_of_interest.csv"
FSA_PROJECTED_POP_DIR = PROJECT_ROOT / "data" / "population" / "fsa_projected_pop"
MAP_EXTENT_SCALE = 1.50
URBAN_PADDING_RATIO = 0.10
URBAN_RIGHT_CROP_RATIO = -0.12
COLOR_GAMMA = 0.55
MAP_SIMPLIFICATION_TOLERANCE = 100.0
CUSTOM_ADOPTION_SCENARIO = "CUSTOM_ADOPTION"
CUSTOM_ADOPTION_BASE_SCENARIO = "bau"
URBAN_FOCUS_FSA_CODES = {
    "G1B",
    "G1C",
    "G1E",
    "G1G",
    "G1H",
    "G1J",
    "G1K",
    "G1L",
    "G1M",
    "G1N",
    "G1P",
    "G1R",
    "G1S",
    "G1T",
    "G1V",
    "G1W",
    "G1X",
    "G1Y",
    "G2G",
    "G2J",
    "G2K",
    "G6W",
}
ProgressCallback = Callable[[int, int, str], None]

_PROGRESS: dict[str, dict[str, Any]] = {}
_PROGRESS_LOCK = threading.Lock()


def progress_reporter(task_id: str | None) -> ProgressCallback | None:
    """Return a callback that records step progress for a GUI task."""
    if not task_id:
        return None

    def report(step: int, total: int, message: str) -> None:
        with _PROGRESS_LOCK:
            _PROGRESS[task_id] = {"step": step, "total": total, "message": message}

    return report


def read_progress(task_id: str) -> dict[str, Any]:
    with _PROGRESS_LOCK:
        return dict(_PROGRESS.get(task_id, {}))


def clear_progress(task_id: str | None) -> None:
    if not task_id:
        return
    with _PROGRESS_LOCK:
        _PROGRESS.pop(task_id, None)


def report_progress(
    progress: ProgressCallback | None, step: int, total: int, message: str
) -> None:
    if progress is not None:
        progress(step, total, message)


VEHICLE_DISPLAY_ORDER = (
    "electric",
    "hev_sedan",
    "hev_suv",
    "ice_sedan",
    "ice_suv",
    "ice_van/pickup",
    "truck",
    "defaultVehicleType",
)

VEHICLE_TYPE_ALIAS = {
    "ice_van/pickup": "truck",
    "hev_van/pickup": "truck",
    "unknown": "defaultVehicleType",
    "other": "defaultVehicleType",
}

VEHICLE_TYPE_XML = """
<vehicleTypes xmlns="http://www.matsim.org/files/dtd">
    <vehicleType id="Bus">
        <length meter="18.0"/>
        <width meter="2.5"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">Bus</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="bus"/>
    </vehicleType>
    <vehicleType id="ice_sedan">
        <length meter="7.5"/>
        <width meter="1.0"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">ice_sedan</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="car"/>
    </vehicleType>
    <vehicleType id="ice_suv">
        <length meter="7.5"/>
        <width meter="1.0"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">ice_suv</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="car"/>
    </vehicleType>
    <vehicleType id="hev_sedan">
        <length meter="7.5"/>
        <width meter="1.0"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">hev_sedan</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="car"/>
    </vehicleType>
    <vehicleType id="hev_suv">
        <length meter="7.5"/>
        <width meter="1.0"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">hev_suv</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="car"/>
    </vehicleType>
    <vehicleType id="truck">
        <length meter="7.5"/>
        <width meter="1.0"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">truck</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="car"/>
    </vehicleType>
    <vehicleType id="electric">
        <length meter="7.5"/>
        <width meter="1.0"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">electric</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="car"/>
    </vehicleType>
    <vehicleType id="defaultVehicleType">
        <length meter="7.5"/>
        <width meter="1.0"/>
        <engineInformation>
            <attributes>
                <attribute name="HbefaVehicleCategory" class="java.lang.String">defaultVehicleType</attribute>
                <attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
                <attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
                <attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
            </attributes>
        </engineInformation>
        <networkMode networkMode="car"/>
    </vehicleType>
</vehicleTypes>
"""


@dataclass
class AssignmentResult:
    output_file: Path
    distribution_file: Path
    assigned_count: int
    transit_vehicle_count: int
    type_counts: dict[str, int]
    projected_share: list[dict[str, Any]]
    fallback_fsas: dict[str, int] = field(default_factory=dict)


@dataclass
class FsaShape:
    fsa: str
    parts: list[list[tuple[float, float]]]
    bbox: tuple[float, float, float, float]
    land_area: float | None = None


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def load_config() -> dict[str, Any]:
    source = CONFIG_PATH if CONFIG_PATH.exists() else DEFAULT_CONFIG_PATH
    with source.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")


def list_vehicle_options(config: dict[str, Any]) -> dict[str, Any]:
    historical_dir = resolve_path(config["historical_vehicle_share_dir"])
    predicted_dir = resolve_path(config["predicted_vehicle_share_dir"])
    historical_years: set[int] = set()
    predicted: dict[int, set[str]] = {}

    for path in historical_dir.glob("fsa_vehicle_share_*.*"):
        stem = path.stem
        parts = stem.split("_")
        if parts[-1].isdigit():
            historical_years.add(int(parts[-1]))

    for path in predicted_dir.glob("fsa_vehicle_share_*_*.*"):
        parts = path.stem.split("_")
        if len(parts) >= 5 and parts[-2].isdigit():
            predicted.setdefault(int(parts[-2]), set()).add(parts[-1])
        elif len(parts) >= 4 and parts[-2].isdigit():
            predicted.setdefault(int(parts[-2]), set()).add(parts[-1])
        else:
            year, scenario = parse_predicted_share_name(path.stem)
            if year is not None and scenario:
                predicted.setdefault(year, set()).add(scenario)

    for year, scenarios in predicted.items():
        if CUSTOM_ADOPTION_BASE_SCENARIO in scenarios:
            scenarios.add(CUSTOM_ADOPTION_SCENARIO)

    return {
        "historical_years": sorted(historical_years),
        "predicted_years": sorted(predicted),
        "predicted_scenarios": {
            str(year): sorted(scenarios) for year, scenarios in predicted.items()
        },
    }


def parse_predicted_share_name(stem: str) -> tuple[int | None, str | None]:
    prefix = "fsa_vehicle_share_"
    if not stem.startswith(prefix):
        return None, None
    rest = stem[len(prefix) :]
    year_text, _, scenario = rest.partition("_")
    if not year_text.isdigit() or not scenario:
        return None, None
    return int(year_text), scenario


def vehicle_distribution_path(
    config: dict[str, Any], year: int, source: str, scenario: str
) -> Path:
    if source == "predicted":
        scenario = (
            CUSTOM_ADOPTION_BASE_SCENARIO
            if scenario == CUSTOM_ADOPTION_SCENARIO
            else scenario
        )
        base = resolve_path(config["predicted_vehicle_share_dir"]) / (
            f"fsa_vehicle_share_{year}_{scenario}"
        )
    else:
        base = resolve_path(config["historical_vehicle_share_dir"]) / (
            f"fsa_vehicle_share_{year}"
        )

    for suffix in (".parquet", ".csv"):
        candidate = base.with_suffix(suffix)
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Vehicle composition file not found: {base}.csv/parquet")


VehicleDistribution = dict[str, list[tuple[str, float]]]


def vehicle_rows_from_frame(frame: Any) -> VehicleDistribution:
    if "fsa" in frame.columns:
        frame = frame.set_index("fsa")
    frame.index = frame.index.astype(str).str.upper()
    result: VehicleDistribution = {}
    for fsa, row in frame.iterrows():
        vehicles: list[tuple[str, float]] = []
        for vehicle_type, value in row.items():
            try:
                probability = float(value)
            except (TypeError, ValueError):
                probability = 0.0
            if probability > 0:
                vehicles.append((str(vehicle_type), probability))
        result[str(fsa)] = vehicles
    return result


def read_vehicle_distribution(path: Path) -> VehicleDistribution:
    if path.suffix == ".parquet":
        import pandas as pd  # Imported lazily so the GUI can start without pandas.

        df = pd.read_parquet(path)
        return vehicle_rows_from_frame(df)

    result: VehicleDistribution = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        if "fsa" in fieldnames:
            fsa_column = "fsa"
        elif fieldnames:
            fsa_column = fieldnames[0]
        else:
            raise ValueError(f"Vehicle composition file has no header: {path}")

        vehicle_columns = [name for name in fieldnames if name != fsa_column]
        for row in reader:
            fsa = (row.get(fsa_column) or "").strip().upper()
            if not fsa:
                continue
            vehicles = []
            for vehicle_type in vehicle_columns:
                try:
                    probability = float(row.get(vehicle_type) or 0)
                except ValueError:
                    probability = 0.0
                if probability > 0:
                    vehicles.append((vehicle_type, probability))
            result[fsa] = vehicles
    return result


def normalized_vehicle_rows(rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    total = sum(max(0.0, probability) for _, probability in rows)
    if total <= 0:
        return []
    return [
        (vehicle_type, max(0.0, probability) / total)
        for vehicle_type, probability in rows
        if probability > 0
    ]


def read_share_frame(path: Path):
    import pandas as pd  # Imported lazily so the GUI can start without pandas.

    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path)
    if "fsa" in frame.columns:
        frame = frame.set_index("fsa")
    frame.index = frame.index.astype(str).str.upper()
    return frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def scale_electric_share_row(
    rows: list[tuple[str, float]], ev_factor: float, ev_type: str = "electric"
) -> list[tuple[str, float]]:
    normalized = dict(normalized_vehicle_rows(rows))
    if ev_type not in normalized:
        return list(normalized.items())
    old_ev = min(max(normalized.get(ev_type, 0.0), 0.0), 1.0)
    new_ev = min(max(old_ev * ev_factor, 0.0), 1.0 - 1e-9)
    old_other = 1.0 - old_ev
    new_other = 1.0 - new_ev
    if old_other <= 0:
        return [(ev_type, 1.0)]
    adjusted = {}
    for vehicle_type, share in normalized.items():
        adjusted[vehicle_type] = new_ev if vehicle_type == ev_type else share * new_other / old_other
    return normalized_vehicle_rows(list(adjusted.items()))


def build_custom_projected_distribution(
    config: dict[str, Any],
    year: int,
    scenario: str,
    ev_factor: float = 1.0,
) -> VehicleDistribution:
    """Build projected shares in memory, optionally applying the Gompertz EV factor."""
    baseline_scenario = (
        CUSTOM_ADOPTION_BASE_SCENARIO
        if scenario == CUSTOM_ADOPTION_SCENARIO
        else scenario
    )
    distribution_file = vehicle_distribution_path(config, year, "predicted", baseline_scenario)
    baseline_distribution = read_vehicle_distribution(distribution_file)
    if scenario != CUSTOM_ADOPTION_SCENARIO or abs(ev_factor - 1.0) < 1e-9:
        return {fsa: normalized_vehicle_rows(rows) for fsa, rows in baseline_distribution.items()}

    from matsim_vehicle_type.fleet.composition import (
        apply_ev_gompertz_scenario_from_scaled_target,
    )

    predicted_dir = resolve_path(config["predicted_vehicle_share_dir"])
    year_paths: dict[int, Path] = {}
    for path in predicted_dir.glob(f"fsa_vehicle_share_*_{baseline_scenario}.*"):
        parsed_year, parsed_scenario = parse_predicted_share_name(path.stem)
        if parsed_year is not None and parsed_scenario == baseline_scenario:
            year_paths[parsed_year] = path

    required_years = {year, 2024, 2035}
    if not required_years.issubset(year_paths):
        return {
            fsa: scale_electric_share_row(rows, ev_factor)
            for fsa, rows in baseline_distribution.items()
        }

    frames = {frame_year: read_share_frame(path) for frame_year, path in sorted(year_paths.items())}
    target_frame = frames[year]
    vehicle_columns = list(target_frame.columns)
    result: VehicleDistribution = {}

    for fsa in target_frame.index:
        fsa_rows: dict[str, list[float]] = {vehicle_type: [] for vehicle_type in vehicle_columns}
        usable = True
        for frame_year in sorted(frames):
            frame = frames[frame_year]
            if fsa not in frame.index:
                usable = False
                break
            row = frame.loc[fsa]
            row_total = float(row.sum())
            if row_total <= 0:
                usable = False
                break
            for vehicle_type in vehicle_columns:
                fsa_rows[vehicle_type].append(float(row.get(vehicle_type, 0.0)) / row_total)
        if not usable:
            result[fsa] = scale_electric_share_row(baseline_distribution.get(fsa, []), ev_factor)
            continue

        import pandas as pd

        matrix = pd.DataFrame(fsa_rows, index=sorted(frames)).T
        try:
            adjusted = apply_ev_gompertz_scenario_from_scaled_target(
                matrix,
                target_factor=ev_factor,
                anchor_year=2024,
                target_year=2035,
                ceiling=1.0,
            )
            result[fsa] = normalized_vehicle_rows(
                [(vehicle_type, float(adjusted.loc[vehicle_type, year])) for vehicle_type in adjusted.index]
            )
        except Exception:
            result[fsa] = scale_electric_share_row(baseline_distribution.get(fsa, []), ev_factor)

    return result


def assignment_distribution(
    config: dict[str, Any],
    year: int,
    source: str,
    scenario: str,
    ev_factor: float,
) -> tuple[Path, VehicleDistribution]:
    distribution_file = vehicle_distribution_path(config, year, source, scenario)
    if source == "predicted":
        return distribution_file, build_custom_projected_distribution(
            config, year, scenario, ev_factor
        )
    return distribution_file, read_vehicle_distribution(distribution_file)


def read_quebec_city_fsas(path: Path = QUEBEC_CITY_FSA_FILE) -> list[str]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return [
            line.strip().upper()
            for line in stream
            if line.strip() and not line.lower().startswith("fsa")
        ]


def projected_population_dir(config: dict[str, Any]) -> Path:
    value = config.get("fsa_projected_pop_dir")
    return resolve_path(value) if value else FSA_PROJECTED_POP_DIR


def projected_population_for_fsa(
    fsa: str, year: int, population_dir: Path = FSA_PROJECTED_POP_DIR
) -> tuple[float | None, int | None]:
    path = population_dir / f"{fsa.upper()}_projected_pop.csv"
    if not path.exists():
        return None, None
    values: dict[int, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            try:
                values[int(row["year"])] = float(row["persons"])
            except (KeyError, TypeError, ValueError):
                continue
    if not values:
        return None, None
    chosen_year = year if year in values else min(values, key=lambda item: abs(item - year))
    return values[chosen_year], chosen_year


def projected_quebec_city_share(
    config: dict[str, Any],
    year: int,
    scenario: str,
    ev_factor: float = 1.0,
    source: str = "predicted",
) -> list[dict[str, Any]]:
    _, distribution = assignment_distribution(config, year, source, scenario, ev_factor)
    target_fsas = read_quebec_city_fsas()
    population_dir = projected_population_dir(config)
    weighted: dict[str, float] = {}
    total_weight = 0.0

    for fsa in target_fsas:
        rows = normalized_vehicle_rows(distribution.get(fsa, []))
        if not rows:
            continue
        population, _ = projected_population_for_fsa(fsa, year, population_dir)
        weight = population if population and population > 0 else 1.0
        total_weight += weight
        for vehicle_type, share in rows:
            weighted[vehicle_type] = weighted.get(vehicle_type, 0.0) + share * weight

    if total_weight <= 0:
        return []

    def sort_key(item: tuple[str, float]) -> tuple[int, str]:
        try:
            return VEHICLE_DISPLAY_ORDER.index(item[0]), item[0]
        except ValueError:
            return len(VEHICLE_DISPLAY_ORDER), item[0]

    return [
        {
            "vehicle_type": vehicle_type,
            "label": vehicle_type,
            "share": value / total_weight,
        }
        for vehicle_type, value in sorted(weighted.items(), key=sort_key)
    ]


def list_assignment_vehicle_files(config: dict[str, Any]) -> list[dict[str, Any]]:
    output_dir = resolve_path(config["output_dir"])
    files = [
        path
        for path in output_dir.glob("vehicles_*.xml*")
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return [
        {
            "path": display_path(path),
            "name": path.name,
            "mtime": path.stat().st_mtime,
        }
        for path in files
    ]


def read_fsa_lookup(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        if {"agent_id", "fsa"}.issubset(fieldnames):
            agent_column, fsa_column = "agent_id", "fsa"
        elif "" in fieldnames and "CFSAUID" in fieldnames:
            agent_column, fsa_column = "", "CFSAUID"
        else:
            raise ValueError(f"Unexpected FSA lookup columns: {fieldnames}")
        return {
            (row.get(agent_column) or "").strip(): (row.get(fsa_column) or "").strip().upper()
            for row in reader
            if (row.get(agent_column) or "").strip()
        }


def choose_vehicle_type(
    fsa: str, distribution: VehicleDistribution, rng: random.Random
) -> str:
    vehicles = distribution.get(fsa or "")
    if vehicles is None:
        vehicles = next(iter(distribution.values()), [])
    if not vehicles:
        return "defaultVehicleType"
    vehicle_type = rng.choices(
        tuple(vehicle_type for vehicle_type, _ in vehicles),
        weights=tuple(probability for _, probability in vehicles),
        k=1,
    )[0]
    return VEHICLE_TYPE_ALIAS.get(vehicle_type, vehicle_type)


def replace_vehicle_type_definitions(root: ET.Element) -> None:
    new_root = ET.fromstring(VEHICLE_TYPE_XML)
    new_types = list(new_root)
    new_type_ids = {vehicle_type.get("id") for vehicle_type in new_types}

    for child in list(root):
        if child.tag.endswith("vehicleType") and child.get("id") in new_type_ids:
            root.remove(child)

    children = list(root)
    insert_at = next(
        (idx for idx, child in enumerate(children) if child.tag.endswith("vehicle")),
        len(children),
    )
    for vehicle_type in new_types:
        root.insert(insert_at, vehicle_type)
        insert_at += 1


def append_transit_vehicles(root: ET.Element, transit_vehicle_file: Path) -> int:
    with open_text(transit_vehicle_file) as stream:
        transit_root = ET.parse(stream).getroot()

    existing_ids = {
        child.get("id")
        for child in root
        if child.tag.endswith("vehicle") and child.get("id")
    }
    appended_count = 0

    for child in transit_root:
        if not child.tag.endswith("vehicle"):
            continue
        vehicle_id = child.get("id")
        if not vehicle_id or vehicle_id in existing_ids:
            continue
        root.append(deepcopy(child))
        existing_ids.add(vehicle_id)
        appended_count += 1

    return appended_count


def assign_vehicle_types(
    config: dict[str, Any],
    year: int,
    source: str,
    scenario: str,
    seed: int,
    ev_factor: float = 1.0,
    output_name: str | None = None,
    progress: ProgressCallback | None = None,
) -> AssignmentResult:
    population_file = resolve_path(config["population_file"])
    vehicle_file = resolve_path(config["vehicle_file"])
    transit_vehicle_file = resolve_path(config["transit_vehicle_file"])
    fsa_lookup_file = resolve_path(config["fsa_lookup_file"])
    output_dir = resolve_path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    report_progress(progress, 1, 4, "Loading vehicle composition")
    distribution_file, distribution = assignment_distribution(
        config, year, source, scenario, ev_factor
    )
    fsa_lookup = read_fsa_lookup(fsa_lookup_file)
    rng = random.Random(seed)

    report_progress(progress, 2, 4, "Reading MATSim population")
    with open_text(population_file) as stream:
        pop_tree = ET.parse(stream)
    person_vehicle: dict[str, str] = {}
    type_counts: dict[str, int] = {}
    fallback_fsas: dict[str, int] = {}
    for person in pop_tree.getroot().findall(".//person"):
        person_id = person.get("id")
        if not person_id:
            continue
        vehicle_type = choose_vehicle_type(fsa_lookup.get(person_id, ""), distribution, rng)
        person_vehicle[person_id] = vehicle_type
        type_counts[vehicle_type] = type_counts.get(vehicle_type, 0) + 1
        home_fsa = fsa_lookup.get(person_id, "")
        if home_fsa not in distribution:
            fallback_fsas[home_fsa or "(no FSA)"] = fallback_fsas.get(home_fsa or "(no FSA)", 0) + 1

    report_progress(progress, 3, 4, "Updating MATSim vehicle file")
    with open_text(vehicle_file) as stream:
        vehicle_tree = ET.parse(stream)
    vehicle_root = vehicle_tree.getroot()
    replace_vehicle_type_definitions(vehicle_root)
    for child in vehicle_root:
        if child.tag.endswith("vehicle"):
            vehicle_id = child.get("id")
            if vehicle_id in person_vehicle:
                child.set("type", person_vehicle[vehicle_id])
    transit_vehicle_count = append_transit_vehicles(vehicle_root, transit_vehicle_file)

    scenario_label = scenario if source == "predicted" else "HISTORICAL"
    factor_label = ""
    if (
        source == "predicted"
        and scenario == CUSTOM_ADOPTION_SCENARIO
        and abs(ev_factor - 1.0) >= 1e-9
    ):
        factor_label = f"_evfactor{ev_factor:.2f}"
    if output_name:
        output_file = output_dir / output_name
    else:
        output_file = output_dir / f"vehicles_{year}_{scenario_label}{factor_label}_seed{seed}.xml"

    report_progress(progress, 4, 4, "Writing assigned vehicle file")
    ET.register_namespace("", "http://www.matsim.org/files/dtd")
    vehicle_tree.write(output_file, encoding="utf-8", xml_declaration=True)

    return AssignmentResult(
        output_file=output_file,
        distribution_file=distribution_file,
        assigned_count=len(person_vehicle),
        transit_vehicle_count=transit_vehicle_count,
        type_counts=dict(sorted(type_counts.items())),
        fallback_fsas=dict(sorted(fallback_fsas.items())),
        projected_share=projected_quebec_city_share(
            config, year, scenario, ev_factor, source=source
        ),
    )


def load_script_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def read_top_rows(path: Path, value_column: str, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row.get("fsa") or "").upper()
            if not fsa or fsa == "UNKNOWN":
                continue
            value = float(row[value_column])
            rows.append({"fsa": fsa, "value": value})
    rows.sort(key=lambda item: item["value"], reverse=True)
    return rows[:limit]


def read_result_values(path: Path, value_column: str) -> dict[str, float]:
    values: dict[str, float] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row.get("fsa") or "").strip().upper()
            if not fsa or fsa == "UNKNOWN":
                continue
            try:
                values[fsa] = float(row[value_column])
            except (KeyError, TypeError, ValueError):
                continue
    return values


def count_fsa_items(items: Any, fsa_by_agent: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        fsa = (fsa_by_agent.get(str(item)) or "").upper()
        if not fsa or fsa == "UNKNOWN":
            continue
        counts[fsa] = counts.get(fsa, 0) + 1
    return counts


def count_ev_vehicles_by_fsa(
    electric_vehicles: set[str],
    agent_by_vehicle: dict[str, str],
    fsa_by_agent: dict[str, str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for vehicle_id in electric_vehicles:
        agent_id = agent_by_vehicle.get(vehicle_id, vehicle_id)
        fsa = (fsa_by_agent.get(agent_id) or "").upper()
        if not fsa or fsa == "UNKNOWN":
            continue
        counts[fsa] = counts.get(fsa, 0) + 1
    return counts


def read_dbf_records(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError(f"Invalid DBF header: {path}")
        num_records = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]

        fields: list[tuple[str, int]] = []
        while stream.tell() < header_length - 1:
            descriptor = stream.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii").strip()
            length = descriptor[16]
            fields.append((name, length))

        stream.seek(header_length)
        records = []
        for _ in range(num_records):
            raw = stream.read(record_length)
            if len(raw) < record_length or raw[:1] == b"*":
                continue
            offset = 1
            record = {}
            for name, length in fields:
                value = raw[offset : offset + length].decode("latin1").strip()
                record[name] = value
                offset += length
            records.append(record)

    return [name for name, _ in fields], records


def read_fsa_shapes(shp_path: Path) -> list[FsaShape]:
    dbf_path = shp_path.with_suffix(".dbf")
    fields, records = read_dbf_records(dbf_path)
    if "CFSAUID" not in fields:
        raise ValueError(f"{dbf_path} must contain CFSAUID; got {fields}")

    shapes: list[FsaShape] = []
    with shp_path.open("rb") as stream:
        header = stream.read(100)
        if len(header) != 100:
            raise ValueError(f"Invalid shapefile header: {shp_path}")

        record_index = 0
        while True:
            record_header = stream.read(8)
            if not record_header:
                break
            if len(record_header) != 8:
                raise ValueError(f"Truncated shapefile record header: {shp_path}")
            content_length = struct.unpack(">i", record_header[4:8])[0] * 2
            content = stream.read(content_length)
            if len(content) != content_length:
                raise ValueError(f"Truncated shapefile record content: {shp_path}")

            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type in {5, 15, 25, 31}:
                minx, miny, maxx, maxy = struct.unpack("<4d", content[4:36])
                num_parts, num_points = struct.unpack("<2i", content[36:44])
                parts_start = 44
                points_start = parts_start + (num_parts * 4)
                part_indices = list(
                    struct.unpack(f"<{num_parts}i", content[parts_start:points_start])
                )
                points = [
                    struct.unpack(
                        "<2d",
                        content[points_start + i * 16 : points_start + (i + 1) * 16],
                    )
                    for i in range(num_points)
                ]
                part_indices.append(num_points)
                parts = [
                    points[part_indices[index] : part_indices[index + 1]]
                    for index in range(num_parts)
                ]
                record = records[record_index]
                fsa = record["CFSAUID"].strip().upper()
                try:
                    land_area = float(record.get("LANDAREA") or "")
                except ValueError:
                    land_area = None
                shapes.append(
                    FsaShape(
                        fsa=fsa,
                        parts=parts,
                        bbox=(minx, miny, maxx, maxy),
                        land_area=land_area,
                    )
                )

            record_index += 1

    return shapes


def boxes_intersect(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] < right[0]
        or left[0] > right[2]
        or left[3] < right[1]
        or left[1] > right[3]
    )


def polygon_bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
    nearest_x = sx + t * dx
    nearest_y = sy + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def simplify_polyline(
    points: list[tuple[float, float]],
    tolerance: float = MAP_SIMPLIFICATION_TOLERANCE,
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points

    closed = points[0] == points[-1]
    work_points = points[:-1] if closed else points
    if len(work_points) <= 2:
        simplified = work_points
    else:
        stack: list[tuple[int, int]] = [(0, len(work_points) - 1)]
        keep = {0, len(work_points) - 1}
        while stack:
            start_index, end_index = stack.pop()
            start = work_points[start_index]
            end = work_points[end_index]
            max_distance = -1.0
            max_index = start_index
            for index in range(start_index + 1, end_index):
                distance = point_segment_distance(work_points[index], start, end)
                if distance > max_distance:
                    max_distance = distance
                    max_index = index
            if max_distance > tolerance:
                keep.add(max_index)
                stack.append((start_index, max_index))
                stack.append((max_index, end_index))
        simplified = [work_points[index] for index in sorted(keep)]

    if closed and simplified and simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return simplified


def bounds_for_map_shapes(shapes: list[FsaShape], values: dict[str, float]) -> tuple[float, float, float, float]:
    selected = [shape for shape in shapes if shape.fsa in URBAN_FOCUS_FSA_CODES]
    if not selected:
        selected = [shape for shape in shapes if shape.fsa in values]
    if not selected:
        raise ValueError("No FSA polygons matched the result summary.")

    minx = min(shape.bbox[0] for shape in selected)
    miny = min(shape.bbox[1] for shape in selected)
    maxx = max(shape.bbox[2] for shape in selected)
    maxy = max(shape.bbox[3] for shape in selected)
    dx = maxx - minx
    dy = maxy - miny
    maxx -= dx * URBAN_RIGHT_CROP_RATIO
    minx -= dx * URBAN_PADDING_RATIO
    miny -= dy * URBAN_PADDING_RATIO
    maxx += dx * URBAN_PADDING_RATIO
    maxy += dy * URBAN_PADDING_RATIO

    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    half_width = (maxx - minx) * MAP_EXTENT_SCALE / 2
    half_height = (maxy - miny) * MAP_EXTENT_SCALE / 2
    return (
        cx - half_width,
        cy - half_height,
        cx + half_width,
        cy + half_height,
    )


def nice_ticks(max_value: float, count: int = 5) -> list[float]:
    if max_value <= 0:
        return [0.0]
    magnitude = 10 ** math.floor(math.log10(max_value))
    residual = max_value / magnitude
    if residual <= 1:
        nice_max = magnitude
    elif residual <= 2:
        nice_max = 2 * magnitude
    elif residual <= 5:
        nice_max = 5 * magnitude
    else:
        nice_max = 10 * magnitude
    return [nice_max * index / (count - 1) for index in range(count)]


def build_fsa_map_payload(
    result_csv: Path,
    shapefile: Path,
    population_year: int,
    metric_column: str,
    unit: str,
    relevant_vehicle_counts: dict[str, int] | None = None,
    per_vehicle_unit: str = "",
    population_dir: Path = FSA_PROJECTED_POP_DIR,
) -> dict[str, Any]:
    values = read_result_values(result_csv, metric_column)
    relevant_vehicle_counts = relevant_vehicle_counts or {}
    shapes = read_fsa_shapes(shapefile)
    bounds = bounds_for_map_shapes(shapes, values)
    max_value = max(values.values() or [0.0])
    visible_shapes = [shape for shape in shapes if boxes_intersect(shape.bbox, bounds)]

    features: list[dict[str, Any]] = []
    original_point_count = 0
    simplified_point_count = 0
    for shape in visible_shapes:
        simplified_parts: list[list[list[float]]] = []
        for part in shape.parts:
            if len(part) < 3:
                continue
            if not boxes_intersect(polygon_bbox(part), bounds):
                continue
            original_point_count += len(part)
            simplified = simplify_polyline(part)
            if len(simplified) < 4:
                continue
            simplified_point_count += len(simplified)
            simplified_parts.append([[round(x, 2), round(y, 2)] for x, y in simplified])
        if not simplified_parts:
            continue
        has_data = shape.fsa in values
        value = values.get(shape.fsa)
        population, pop_year = projected_population_for_fsa(
            shape.fsa, population_year, population_dir
        )
        relevant_vehicle_count = relevant_vehicle_counts.get(shape.fsa)
        per_vehicle = None
        if value is not None and relevant_vehicle_count and relevant_vehicle_count > 0:
            per_vehicle = value / relevant_vehicle_count
        features.append(
            {
                "fsa": shape.fsa,
                "bbox": [round(number, 2) for number in shape.bbox],
                "parts": simplified_parts,
                "value": value,
                "has_data": has_data,
                "population": population,
                "population_year": pop_year,
                "land_area": shape.land_area,
                "relevant_vehicle_count": relevant_vehicle_count,
                "per_vehicle": per_vehicle,
                "per_vehicle_unit": per_vehicle_unit,
            }
        )

    return {
        "bounds": [round(number, 2) for number in bounds],
        "features": features,
        "metric_column": metric_column,
        "unit": unit,
        "per_vehicle_unit": per_vehicle_unit,
        "max_value": max_value,
        "ticks": nice_ticks(max_value),
        "population_year": population_year,
        "no_data_hatching": True,
        "color_gamma": COLOR_GAMMA,
        "simplification_tolerance": MAP_SIMPLIFICATION_TOLERANCE,
        "original_point_count": original_point_count,
        "simplified_point_count": simplified_point_count,
    }


def set_config_param(root: ET.Element, module_name: str, param_name: str, value: str) -> None:
    for module in root.findall("module"):
        if module.get("name") != module_name:
            continue
        for param in module.findall("param"):
            if param.get("name") == param_name:
                param.set("value", value)
                return
        ET.SubElement(module, "param", {"name": param_name, "value": value})
        return
    module = ET.SubElement(root, "module", {"name": module_name})
    ET.SubElement(module, "param", {"name": param_name, "value": value})


def emission_output_label(year: int, scenario: str) -> str:
    clean_scenario = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in scenario
    )
    return f"{year}_{clean_scenario}"


def write_matsim_config(tree: ET.ElementTree, path: Path) -> None:
    root_xml = ET.tostring(tree.getroot(), encoding="unicode")
    path.write_text(
        "\n".join(
            (
                '<?xml version="1.0" encoding="UTF-8"?>',
                MATSIM_CONFIG_DOCTYPE,
                root_xml,
                "",
            )
        ),
        encoding="utf-8",
    )


def create_emission_run_config(
    config: dict[str, Any],
    year: int,
    scenario: str,
    vehicle_file: str,
) -> tuple[Path, Path]:
    template_path = resolve_path(config["emission_config_template"])
    config_dir = resolve_path(config["emission_config_dir"])
    emission_events_dir = resolve_path(config["emission_events_dir"])
    run_label = emission_output_label(year, scenario)
    run_output_dir = emission_events_dir / run_label
    config_dir.mkdir(parents=True, exist_ok=True)
    run_output_dir.mkdir(parents=True, exist_ok=True)

    tree = ET.parse(template_path)
    root = tree.getroot()
    module_root = resolve_path(config["emission_module_dir"])
    factor_dir = module_root / "QC_input_data" / "emission_factor_table"

    set_config_param(root, "controller", "outputDirectory", str(run_output_dir) + "/")
    set_config_param(root, "network", "inputNetworkFile", str(resolve_path(config["network_file"])))
    set_config_param(root, "plans", "inputPlansFile", str(resolve_path(config["population_file"])))
    set_config_param(root, "vehicles", "vehiclesFile", str(resolve_path(vehicle_file)))
    set_config_param(
        root,
        "emissions",
        "averageFleetColdEmissionFactorsFile",
        str(factor_dir / "hbefa_cold_emission_factor_table.csv"),
    )
    set_config_param(
        root,
        "emissions",
        "averageFleetWarmEmissionFactorsFile",
        str(factor_dir / "warm_emission_factor_table0416.csv"),
    )

    generated_config = config_dir / f"config_average_{run_label}.xml"
    write_matsim_config(tree, generated_config)
    return generated_config, run_output_dir / "emission.events.offline.xml.gz"


def run_emission_module(
    config: dict[str, Any],
    year: int,
    scenario: str,
    vehicle_file: str,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    maven_command = next(
        (candidate for candidate in MAVEN_CANDIDATES if shutil.which(candidate)),
        None,
    )
    if maven_command is None:
        raise RuntimeError(
            "Maven is required to run the MATSim emission module, but 'mvn' was not found on PATH."
        )

    emission_module_dir = resolve_path(config["emission_module_dir"])
    events_file = resolve_path(config["matsim_events_file"])
    report_progress(progress, 1, 2, "Writing emission run configuration")
    generated_config, emission_events_file = create_emission_run_config(
        config, year, scenario, vehicle_file
    )
    command = [
        maven_command,
        "-q",
        "exec:java",
        f"-Dexec.mainClass={AVERAGE_EMISSION_MAIN_CLASS}",
        f"-Demission.events.input={events_file}",
        f"-Dexec.args={generated_config}",
    ]
    report_progress(progress, 2, 2, "Running MATSim emission module")
    completed = subprocess.run(
        command,
        cwd=emission_module_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        tail = "\n".join((completed.stderr or completed.stdout).splitlines()[-30:])
        raise RuntimeError(f"Emission module failed with code {completed.returncode}:\n{tail}")
    if not emission_events_file.exists():
        raise FileNotFoundError(f"Emission module did not create {emission_events_file}")

    config["emission_events_file"] = display_path(emission_events_file)
    return {
        "emission_events_file": display_path(emission_events_file),
        "emission_config_file": display_path(generated_config),
        "vehicle_file": vehicle_file,
        "events_file": display_path(events_file),
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-12:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-12:]),
    }


def emission_events_for_scenario(config: dict[str, Any], year: int, scenario: str) -> Path:
    """Prefer emission events produced for this year and scenario.

    Looks for the emission module output folder first, then for the
    ``emission.events.offline.<year>.<scenario>.xml.gz`` naming used by the
    post-processing scripts, and falls back to the configured file.
    """
    events_dir = resolve_path(config["emission_events_dir"])
    candidates = (
        events_dir / emission_output_label(year, scenario) / "emission.events.offline.xml.gz",
        events_dir / f"emission.events.offline.{year}.{scenario}.xml.gz",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return resolve_path(config["emission_events_file"])


def generate_co2_results(
    config: dict[str, Any],
    year: int,
    scenario: str,
    emission_events_file: str | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    module = load_script_module(
        "platform_co2_results",
        PROJECT_ROOT / "data_post-processing" / "summarize_fsa_co2_emissions.py",
    )
    output_dir = resolve_path(config["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = (
        resolve_path(emission_events_file)
        if emission_events_file
        else emission_events_for_scenario(config, year, scenario)
    )
    fsa_lookup = module.read_fsa_csv(resolve_path(config["fsa_lookup_file"]))

    report_progress(progress, 1, 4, "Reading emission events")
    co2_by_agent, co2_by_fsa, agent_by_vehicle, events, unmatched = (
        module.summarize_emission_events(events_path, fsa_lookup)
    )
    fsa_csv = output_dir / f"co2_emissions_by_fsa_{year}_{scenario}.csv"
    agent_csv = output_dir / f"co2_emissions_by_agent_{year}_{scenario}.csv"
    heatmap = output_dir / f"co2_emissions_by_fsa_{year}_{scenario}.png"
    report_progress(progress, 2, 4, "Writing CO2 tables")
    module.write_agent_csv(agent_csv, str(year), scenario, co2_by_agent, fsa_lookup)
    module.write_fsa_csv(fsa_csv, str(year), scenario, co2_by_fsa)
    max_value = module.max_co2_value([fsa_csv])
    report_progress(progress, 3, 4, "Rendering heatmap image")
    module.plot_fsa_heatmap(
        fsa_csv,
        resolve_path(config["fsa_shapefile"]),
        heatmap,
        str(year),
        scenario,
        shared_max_value=max_value,
        crop_to_urban=True,
    )
    relevant_vehicle_counts = count_fsa_items(co2_by_agent.keys(), fsa_lookup)
    report_progress(progress, 4, 4, "Building interactive map")

    return {
        "metric": "CO2 emissions",
        "unit": "t/day",
        "events": events,
        "vehicle_agent_mappings": len(agent_by_vehicle),
        "unmatched_events": unmatched,
        "csv": display_path(fsa_csv),
        "agent_csv": display_path(agent_csv),
        "heatmap": display_path(heatmap),
        "emission_events_file": display_path(events_path),
        "top_fsa": read_top_rows(fsa_csv, "co2_t_per_day"),
        "map": build_fsa_map_payload(
            fsa_csv,
            resolve_path(config["fsa_shapefile"]),
            year,
            "co2_t_per_day",
            "t/day",
            relevant_vehicle_counts=relevant_vehicle_counts,
            per_vehicle_unit="t/day/vehicle",
            population_dir=projected_population_dir(config),
        ),
    }


def generate_ev_results(
    config: dict[str, Any],
    year: int,
    scenario: str,
    vehicle_file: str,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    module = load_script_module(
        "platform_ev_results",
        PROJECT_ROOT / "data_post-processing" / "summarize_ev_electricity_by_scenario.py",
    )
    output_dir = resolve_path(config["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    vehicle_path = resolve_path(vehicle_file)
    events_path = resolve_path(config["matsim_events_file"])
    network_path = resolve_path(config["network_file"])
    fsa_file = resolve_path(config["fsa_lookup_file"])

    historical_year = 2020 if int(year) == 2020 else 2024
    shares = module.read_historical_shares(
        resolve_path(config["historical_bev_share_file"]), historical_year
    )
    report_progress(progress, 1, 5, "Reading assigned vehicle file")
    electric_vehicles = module.read_electric_vehicles(vehicle_path)
    report_progress(progress, 2, 5, "Reading network and MATSim events")
    link_lengths = module.read_link_lengths(network_path)
    vehicle_metres, agent_by_vehicle, missing_links = module.summarize_event_distances(
        events_path, electric_vehicles, link_lengths
    )
    fsa_by_agent = module.read_fsa_csv(fsa_file)
    report_progress(progress, 3, 5, "Writing electricity tables")
    fsa_csv, type_csv = module.write_fsa_and_type_csvs(
        str(year),
        scenario,
        electric_vehicles,
        vehicle_metres,
        agent_by_vehicle,
        fsa_by_agent,
        shares,
        output_dir,
    )
    max_value = max(module.read_map_values(fsa_csv).values() or [0])
    heatmap = fsa_csv.with_suffix(".png")
    report_progress(progress, 4, 5, "Rendering heatmap image")
    module.plot_fsa_heatmap(fsa_csv, heatmap, max_value)
    relevant_vehicle_counts = count_ev_vehicles_by_fsa(
        electric_vehicles, agent_by_vehicle, fsa_by_agent
    )
    report_progress(progress, 5, 5, "Building interactive map")

    return {
        "metric": "EV electricity demand",
        "unit": "GWh/year",
        "electric_vehicles": len(electric_vehicles),
        "vehicles_with_mileage": len(vehicle_metres),
        "missing_link_events": missing_links,
        "csv": display_path(fsa_csv),
        "type_csv": display_path(type_csv),
        "heatmap": display_path(heatmap),
        "vehicle_file": display_path(vehicle_path),
        "top_fsa": read_top_rows(fsa_csv, "electricity_gwh_per_year"),
        "map": build_fsa_map_payload(
            fsa_csv,
            resolve_path(config["fsa_shapefile"]),
            year,
            "electricity_gwh_per_year",
            "GWh/year",
            relevant_vehicle_counts=relevant_vehicle_counts,
            per_vehicle_unit="GWh/year/EV",
            population_dir=projected_population_dir(config),
        ),
    }


def existing_result_options(config: dict[str, Any]) -> list[dict[str, str]]:
    results_dir = resolve_path(config["results_dir"])
    options: list[dict[str, str]] = []
    patterns = [
        ("CO2 emissions", "co2_emissions_by_fsa_", "co2_t_per_day"),
        ("EV electricity demand", "ev_electricity_by_fsa_", "electricity_gwh_per_year"),
    ]
    for metric, prefix, value_column in patterns:
        for csv_path in sorted(results_dir.glob(f"{prefix}*.csv")):
            if csv_path.name.endswith("_all_scenarios.csv"):
                continue
            suffix = csv_path.stem[len(prefix) :]
            year, _, scenario = suffix.partition("_")
            heatmap = csv_path.with_suffix(".png")
            options.append(
                {
                    "metric": metric,
                    "year": year,
                    "scenario": scenario,
                    "csv": display_path(csv_path),
                    "heatmap": display_path(heatmap) if heatmap.exists() else "",
                    "value_column": value_column,
                }
            )
    return options
