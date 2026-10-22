#!/usr/bin/env python3
"""
Estimate EV electricity use by scenario from MATSim events and vehicle files.

The events file is one simulated day. Results are expanded from the 10% MATSim
sample to full population and annualized:

    kWh/year = km/day * kWh/km * 365 * 10

EVs are deterministically assigned to three BEV body-type classes by scenario:
passenger cars, multi-purpose vehicles, and a combined pickup truck/van class.
The 2020 REF scenario uses historical 2020 Quebec BEV type shares; 2035
scenarios use historical 2024 Quebec BEV type shares.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import math
import struct
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = SCRIPT_DIR / "results"

EVENTS_FILE = PROJECT_ROOT / "data" / "MATSim" / "events" / "output_events.xml.gz"
NETWORK_FILE = PROJECT_ROOT / "data" / "MATSim" / "network" / "network_0409.xml"
FSA_FILE = PROJECT_ROOT / "data" / "FSA" / "agent_id_fsa_table.csv"
FSA_SHAPEFILE = PROJECT_ROOT / "data" / "FSA" / "quebec_fsa" / "quebec_fsa.shp"
HISTORICAL_SHARE_FILE = RESULTS_DIR / "battery_electric_vehicle_type_share_quebec.csv"

SCENARIOS = [
    ("2020", "REF", PROJECT_ROOT / "output" / "vehicles_2020_REF.xml"),
    ("2035", "bau", PROJECT_ROOT / "output" / "vehicles_2035_bau.xml"),
    (
        "2035",
        "del_adopt",
        PROJECT_ROOT / "output" / "vehicles_2035_del_adopt.xml",
    ),
    (
        "2035",
        "pol_align",
        PROJECT_ROOT / "output" / "vehicles_2035_pol_align.xml",
    ),
    (
        "2035",
        "acc_adopt",
        PROJECT_ROOT / "output" / "vehicles_2035_acc_adopt.xml",
    ),
]

SAMPLE_EXPANSION_FACTOR = 10
DAYS_PER_YEAR = 365
EV_VEHICLE_TYPE = "electric"
URBAN_PADDING_RATIO = 0.0
URBAN_RIGHT_CROP_RATIO = -0.07
MAP_IMAGE_WIDTH = 1000
MAP_IMAGE_HEIGHT = 900
DRAW_LEGEND = True

KWH_PER_KM_BY_TYPE = {
    "Passenger cars": 0.18,
    "Multi-purpose vehicles": 0.23,
    "Pickup trucks and vans": 0.30,
}

SOURCE_TYPE_TO_MODEL_TYPE = {
    "Passenger cars": "Passenger cars",
    "Multi-purpose vehicles": "Multi-purpose vehicles",
    "Pickup trucks": "Pickup trucks and vans",
    "Vans": "Pickup trucks and vans",
}

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


@dataclass
class FsaShape:
    fsa: str
    parts: list[list[tuple[float, float]]]
    bbox: tuple[float, float, float, float]


def open_text(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def iter_elements(path: Path, wanted_tag: str):
    with open_text(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if local_name(elem.tag) == wanted_tag:
                yield elem
            elem.clear()


def read_electric_vehicles(path: Path) -> set[str]:
    vehicles = set()
    for elem in iter_elements(path, "vehicle"):
        if elem.get("type") == EV_VEHICLE_TYPE and elem.get("id"):
            vehicles.add(elem.get("id"))
    return vehicles


def read_link_lengths(path: Path) -> dict[str, float]:
    lengths = {}
    for elem in iter_elements(path, "link"):
        link_id = elem.get("id")
        length = elem.get("length")
        if link_id and length:
            lengths[link_id] = float(length)
    return lengths


def read_fsa_csv(path: Path) -> dict[str, str]:
    result = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        if {"agent_id", "fsa"}.issubset(fieldnames):
            agent_column, fsa_column = "agent_id", "fsa"
        elif "" in fieldnames and "CFSAUID" in fieldnames:
            agent_column, fsa_column = "", "CFSAUID"
        else:
            raise ValueError(f"Unexpected FSA CSV columns: {fieldnames}")
        for row in reader:
            agent_id = (row.get(agent_column) or "").strip()
            fsa = (row.get(fsa_column) or "").strip().upper()
            if agent_id:
                result[agent_id] = fsa or "UNKNOWN"
    return result


def read_historical_shares(path: Path, year: int) -> dict[str, float]:
    shares = {vehicle_type: 0.0 for vehicle_type in KWH_PER_KM_BY_TYPE}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            if int(row["year"]) != year:
                continue
            model_type = SOURCE_TYPE_TO_MODEL_TYPE.get(row["vehicle_type"])
            if model_type:
                shares[model_type] += float(row["share_of_all_bev"])
    return normalize_shares(shares)


def normalize_shares(shares: dict[str, float]) -> dict[str, float]:
    total = sum(shares.values())
    if total <= 0:
        raise ValueError("Vehicle type shares sum to zero.")
    return {vehicle_type: share / total for vehicle_type, share in shares.items()}


def assign_vehicle_type(agent_id: str, scenario: str, shares: dict[str, float]) -> str:
    # Keep the existing random draws when only the scenario name changes.
    draw_scenario = {
        "bau": "BAU",
        "acc_adopt": "ACCELERATED_ADOPTION",
        "del_adopt": "DELAYED_ADOPTION",
        "pol_align": "POLICY_ALIGNED",
    }.get(scenario, scenario)
    digest = hashlib.sha256(f"{draw_scenario}:{agent_id}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") / 2**64
    cumulative = 0.0
    last_type = next(reversed(shares))
    for vehicle_type, probability in shares.items():
        cumulative += probability
        if value <= cumulative:
            return vehicle_type
    return last_type


def summarize_event_distances(
    path: Path,
    electric_vehicle_union: set[str],
    link_lengths: dict[str, float],
) -> tuple[dict[str, float], dict[str, str], int]:
    vehicle_metres = defaultdict(float)
    agent_by_vehicle = {}
    missing_link_events = 0

    with open_text(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if local_name(elem.tag) != "event":
                elem.clear()
                continue

            event_type = (elem.get("type") or "").lower()
            if event_type == "personentersvehicle":
                person = elem.get("person")
                vehicle = elem.get("vehicle")
                if person and vehicle:
                    agent_by_vehicle[vehicle] = person
            elif event_type == "left link":
                vehicle = elem.get("vehicle")
                if vehicle in electric_vehicle_union:
                    length = link_lengths.get(elem.get("link") or "")
                    if length is None:
                        missing_link_events += 1
                    else:
                        vehicle_metres[vehicle] += length
            elem.clear()

    return dict(vehicle_metres), agent_by_vehicle, missing_link_events


def scenario_shares(year: str, historical_2020: dict[str, float], historical_2024: dict[str, float]):
    return historical_2020 if year == "2020" else historical_2024


def write_fsa_and_type_csvs(
    year: str,
    scenario: str,
    electric_vehicles: set[str],
    vehicle_metres: dict[str, float],
    agent_by_vehicle: dict[str, str],
    fsa_by_agent: dict[str, str],
    shares: dict[str, float],
    output_dir: Path,
) -> tuple[Path, Path]:
    fsa_rows = defaultdict(
        lambda: {
            "ev_count": 0,
            "active_ev_count": 0,
            "distance_km_per_day": 0.0,
            "electricity_kwh_per_day": 0.0,
        }
    )
    type_rows = defaultdict(
        lambda: {
            "ev_count": 0,
            "active_ev_count": 0,
            "distance_km_per_day": 0.0,
            "electricity_kwh_per_day": 0.0,
        }
    )

    for vehicle in electric_vehicles:
        agent = agent_by_vehicle.get(vehicle, vehicle)
        fsa = fsa_by_agent.get(agent, "UNKNOWN")
        vehicle_type = assign_vehicle_type(agent, scenario, shares)
        km = vehicle_metres.get(vehicle, 0.0) / 1000
        kwh = km * KWH_PER_KM_BY_TYPE[vehicle_type]

        for target in (fsa_rows[fsa], type_rows[vehicle_type]):
            target["ev_count"] += 1
            target["distance_km_per_day"] += km
            target["electricity_kwh_per_day"] += kwh
            if km > 0:
                target["active_ev_count"] += 1

    fsa_path = output_dir / f"ev_electricity_by_fsa_{year}_{scenario}.csv"
    with fsa_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "year",
                "scenario",
                "fsa",
                "ev_count",
                "active_ev_count",
                "distance_km_per_day_sample",
                "electricity_kwh_per_day_sample",
                "electricity_mwh_per_year",
                "electricity_gwh_per_year",
            ]
        )
        for fsa in sorted(fsa_rows):
            row = fsa_rows[fsa]
            annual_kwh = (
                row["electricity_kwh_per_day"]
                * SAMPLE_EXPANSION_FACTOR
                * DAYS_PER_YEAR
            )
            writer.writerow(
                [
                    year,
                    scenario,
                    fsa,
                    row["ev_count"],
                    row["active_ev_count"],
                    f"{row['distance_km_per_day']:.6f}",
                    f"{row['electricity_kwh_per_day']:.6f}",
                    f"{annual_kwh / 1000:.9f}",
                    f"{annual_kwh / 1_000_000:.9f}",
                ]
            )

    type_path = output_dir / f"ev_electricity_by_vehicle_type_{year}_{scenario}.csv"
    with type_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "year",
                "scenario",
                "vehicle_type",
                "assigned_share",
                "kwh_per_km",
                "ev_count",
                "active_ev_count",
                "distance_km_per_day_sample",
                "electricity_kwh_per_day_sample",
                "electricity_gwh_per_year",
            ]
        )
        for vehicle_type in KWH_PER_KM_BY_TYPE:
            row = type_rows[vehicle_type]
            annual_kwh = (
                row["electricity_kwh_per_day"]
                * SAMPLE_EXPANSION_FACTOR
                * DAYS_PER_YEAR
            )
            writer.writerow(
                [
                    year,
                    scenario,
                    vehicle_type,
                    f"{shares.get(vehicle_type, 0.0):.8f}",
                    f"{KWH_PER_KM_BY_TYPE[vehicle_type]:.3f}",
                    row["ev_count"],
                    row["active_ev_count"],
                    f"{row['distance_km_per_day']:.6f}",
                    f"{row['electricity_kwh_per_day']:.6f}",
                    f"{annual_kwh / 1_000_000:.9f}",
                ]
            )

    return fsa_path, type_path


def read_dbf_records(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("rb") as stream:
        header = stream.read(32)
        num_records = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]
        fields = []
        while stream.tell() < header_length - 1:
            descriptor = stream.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii").strip()
            fields.append((name, descriptor[16]))
        stream.seek(header_length)
        records = []
        for _ in range(num_records):
            raw = stream.read(record_length)
            if len(raw) < record_length or raw[:1] == b"*":
                continue
            offset = 1
            record = {}
            for name, length in fields:
                record[name] = raw[offset : offset + length].decode("latin1").strip()
                offset += length
            records.append(record)
    return [name for name, _ in fields], records


def read_fsa_shapes(shp_path: Path) -> list[FsaShape]:
    _, records = read_dbf_records(shp_path.with_suffix(".dbf"))
    shapes = []
    with shp_path.open("rb") as stream:
        stream.read(100)
        record_index = 0
        while True:
            record_header = stream.read(8)
            if not record_header:
                break
            content_length = struct.unpack(">i", record_header[4:8])[0] * 2
            content = stream.read(content_length)
            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type in {5, 15, 25, 31}:
                minx, miny, maxx, maxy = struct.unpack("<4d", content[4:36])
                num_parts, num_points = struct.unpack("<2i", content[36:44])
                parts_start = 44
                points_start = parts_start + num_parts * 4
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
                    points[part_indices[i] : part_indices[i + 1]]
                    for i in range(num_parts)
                ]
                fsa = records[record_index]["CFSAUID"].strip().upper()
                shapes.append(FsaShape(fsa, parts, (minx, miny, maxx, maxy)))
            record_index += 1
    return shapes


def color_ramp(value: float, max_value: float) -> tuple[int, int, int]:
    if max_value <= 0 or value <= 0:
        return (247, 252, 245)
    t = min(1.0, max(0.0, value / max_value)) ** 0.55
    stops = [
        (247, 252, 245),
        (229, 245, 224),
        (199, 233, 192),
        (161, 217, 155),
        (65, 171, 93),
        (0, 109, 44),
    ]
    scaled = t * (len(stops) - 1)
    idx = min(len(stops) - 2, int(math.floor(scaled)))
    frac = scaled - idx
    a = stops[idx]
    b = stops[idx + 1]
    return tuple(round(a[i] + (b[i] - a[i]) * frac) for i in range(3))


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
    return [nice_max * i / (count - 1) for i in range(count)]


def map_bounds(shapes: list[FsaShape]) -> tuple[float, float, float, float]:
    selected = [shape for shape in shapes if shape.fsa in URBAN_FOCUS_FSA_CODES]
    minx = min(shape.bbox[0] for shape in selected)
    miny = min(shape.bbox[1] for shape in selected)
    maxx = max(shape.bbox[2] for shape in selected)
    maxy = max(shape.bbox[3] for shape in selected)
    dx = maxx - minx
    dy = maxy - miny
    maxx -= dx * URBAN_RIGHT_CROP_RATIO
    return (
        minx - dx * URBAN_PADDING_RATIO,
        miny - dy * URBAN_PADDING_RATIO,
        maxx + dx * URBAN_PADDING_RATIO,
        maxy + dy * URBAN_PADDING_RATIO,
    )


def read_map_values(path: Path) -> dict[str, float]:
    values = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = row["fsa"].upper()
            if fsa != "UNKNOWN":
                values[fsa] = float(row["electricity_gwh_per_year"])
    return values


def plot_fsa_heatmap(csv_path: Path, output_path: Path, shared_max_value: float) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Plotting requires Pillow.") from exc

    values = read_map_values(csv_path)
    shapes = read_fsa_shapes(FSA_SHAPEFILE)
    minx, miny, maxx, maxy = map_bounds(shapes)
    width, height = MAP_IMAGE_WIDTH, MAP_IMAGE_HEIGHT
    legend_width = 220 if DRAW_LEGEND else 0
    map_width = width - legend_width
    map_height = height
    scale = min(map_width / (maxx - minx), map_height / (maxy - miny))
    x_offset = (map_width - (maxx - minx) * scale) / 2
    y_offset = (map_height - (maxy - miny) * scale) / 2

    def transform(point: tuple[float, float]) -> tuple[int, int]:
        x, y = point
        return (
            round(x_offset + (x - minx) * scale),
            round(y_offset + (maxy - y) * scale),
        )

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    tick_values = nice_ticks(shared_max_value)
    vmax = tick_values[-1]

    for shape in shapes:
        value = values.get(shape.fsa)
        fill = color_ramp(value or 0.0, vmax) if value is not None else (235, 235, 235)
        outline = (255, 255, 255) if value is not None else (210, 210, 210)
        for part in shape.parts:
            polygon = [transform(point) for point in part]
            if len(polygon) >= 3:
                draw.polygon(polygon, fill=fill, outline=outline)

    if DRAW_LEGEND:
        font = ImageFont.load_default()
        label_font = ImageFont.load_default(size=16)
        draw.rectangle([width - legend_width, 0, width, height], fill="white")
        legend_x = width - legend_width + 38
        legend_y = 90
        legend_h = min(760, height - legend_y - 80)
        legend_w = 36
        for i in range(legend_h):
            frac = 1 - i / max(1, legend_h - 1)
            draw.rectangle(
                [legend_x, legend_y + i, legend_x + legend_w, legend_y + i],
                fill=color_ramp(frac * vmax, vmax),
            )
        draw.rectangle(
            [legend_x, legend_y, legend_x + legend_w, legend_y + legend_h],
            outline=(90, 90, 90),
        )
        draw.text((legend_x, legend_y - 32), "GWh/year", fill=(30, 30, 30), font=label_font)
        for tick in tick_values:
            y = legend_y + legend_h - (tick / vmax * legend_h if vmax else 0)
            draw.line([legend_x + legend_w, y, legend_x + legend_w + 8, y], fill=(60, 60, 60))
            draw.text(
                (legend_x + legend_w + 14, y),
                f"{tick:.3g}",
                anchor="lm",
                fill=(50, 50, 50),
                font=font,
            )

    image.save(output_path)


def write_total_csv(path: Path, fsa_paths: list[Path]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["year", "scenario", "electricity_gwh_per_year"])
        for fsa_path in fsa_paths:
            total = 0.0
            year = scenario = ""
            with fsa_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    year = row["year"]
                    scenario = row["scenario"]
                    total += float(row["electricity_gwh_per_year"])
            writer.writerow([year, scenario, f"{total:.6f}"])


def plot_total_bar(path: Path, total_csv: Path) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Plotting requires Pillow.") from exc

    rows = []
    with total_csv.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows.extend(reader)
    order = {scenario: idx for idx, (_, scenario, _) in enumerate(SCENARIOS)}
    rows.sort(key=lambda row: order[row["scenario"]])
    width, height = 1500, 900
    ml, mr, mt, mb = 165, 80, 60, 150
    pw, ph = width - ml - mr, height - mt - mb
    values = [float(row["electricity_gwh_per_year"]) for row in rows]
    y_max = nice_ticks(max(values))[-1]

    def y_for(value: float) -> float:
        return mt + ph - value / y_max * ph

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    axis_font = ImageFont.load_default(size=18)
    label_font = ImageFont.load_default(size=20)
    small_font = ImageFont.load_default(size=15)
    for tick in nice_ticks(max(values)):
        y = y_for(tick)
        draw.line([(ml, y), (ml + pw, y)], fill=(225, 225, 225))
        draw.text((ml - 15, y), f"{tick:.0f}", anchor="rm", fill=(50, 50, 50), font=small_font)
    draw.line([(ml, mt), (ml, mt + ph), (ml + pw, mt + ph)], fill=(70, 70, 70), width=2)
    draw.text((55, mt + ph / 2), "GWh/year", anchor="mm", fill=(45, 45, 45), font=axis_font)
    slot = pw / len(rows)
    bar_w = slot * 0.58
    colors = [(229, 245, 224), (199, 233, 192), (161, 217, 155), (65, 171, 93), (0, 109, 44)]
    labels = {
        "REF": "2020 REF",
        "bau": "2035 bau",
        "del_adopt": "2035 Delayed",
        "pol_align": "2035 Policy-aligned",
        "acc_adopt": "2035 Accelerated",
    }
    for idx, row in enumerate(rows):
        value = float(row["electricity_gwh_per_year"])
        cx = ml + slot * (idx + 0.5)
        y0 = y_for(value)
        y1 = mt + ph
        draw.rectangle([cx - bar_w / 2, y0, cx + bar_w / 2, y1], fill=colors[idx], outline="white", width=2)
        draw.text((cx, y0 - 20), f"{value:.1f}", anchor="mm", fill=(25, 25, 25), font=label_font)
        label = labels[row["scenario"]]
        parts = label.split()
        label_text = f"{parts[0]} {parts[1]}" if len(parts) == 2 else f"{parts[0]} {parts[1]}\n{' '.join(parts[2:])}"
        ly = y1 + 24
        for line in label_text.split("\n"):
            draw.text((cx, ly), line, anchor="mm", fill=(35, 35, 35), font=axis_font)
            ly += 24
    image.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate EV electricity use by scenario.")
    parser.add_argument("--plot-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    fsa_paths = [
        RESULTS_DIR / f"ev_electricity_by_fsa_{year}_{scenario}.csv"
        for year, scenario, _ in SCENARIOS
    ]

    if not args.plot_only:
        historical_2020_shares = read_historical_shares(HISTORICAL_SHARE_FILE, 2020)
        historical_2024_shares = read_historical_shares(HISTORICAL_SHARE_FILE, 2024)
        scenario_ev = {
            (year, scenario): read_electric_vehicles(vehicle_file)
            for year, scenario, vehicle_file in SCENARIOS
        }
        electric_union = set().union(*scenario_ev.values())
        print(f"Electric vehicle union: {len(electric_union):,}", file=sys.stderr)

        print("Reading network link lengths...", file=sys.stderr)
        link_lengths = read_link_lengths(NETWORK_FILE)
        print(f"Links: {len(link_lengths):,}", file=sys.stderr)

        print("Streaming MATSim events once...", file=sys.stderr)
        vehicle_metres, agent_by_vehicle, missing = summarize_event_distances(
            EVENTS_FILE, electric_union, link_lengths
        )
        print(
            f"Vehicles with EV mileage: {len(vehicle_metres):,}; missing links: {missing:,}",
            file=sys.stderr,
        )

        fsa_by_agent = read_fsa_csv(FSA_FILE)
        fsa_paths = []
        for year, scenario, _ in SCENARIOS:
            shares = scenario_shares(year, historical_2020_shares, historical_2024_shares)
            fsa_path, type_path = write_fsa_and_type_csvs(
                year,
                scenario,
                scenario_ev[(year, scenario)],
                vehicle_metres,
                agent_by_vehicle,
                fsa_by_agent,
                shares,
                RESULTS_DIR,
            )
            fsa_paths.append(fsa_path)
            print(f"Wrote {fsa_path}", file=sys.stderr)
            print(f"Wrote {type_path}", file=sys.stderr)

    total_csv = RESULTS_DIR / "ev_electricity_total_by_scenario.csv"
    write_total_csv(total_csv, fsa_paths)
    print(f"Wrote {total_csv}", file=sys.stderr)

    shared_max = max(max(read_map_values(path).values()) for path in fsa_paths)
    shared_legend_max = nice_ticks(shared_max)[-1]
    print(f"Using shared heatmap legend max: {shared_legend_max:g} GWh/year", file=sys.stderr)
    for fsa_path in fsa_paths:
        map_path = fsa_path.with_suffix(".png")
        plot_fsa_heatmap(fsa_path, map_path, shared_max)
        print(f"Wrote {map_path}", file=sys.stderr)

    bar_path = RESULTS_DIR / "ev_electricity_total_by_scenario.png"
    plot_total_bar(bar_path, total_csv)
    print(f"Wrote {bar_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
