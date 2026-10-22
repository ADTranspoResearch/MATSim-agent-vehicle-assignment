#!/usr/bin/env python3
"""
Summarize MATSim CO2 emission events by agent FSA and draw heatmaps.

Each emission event file is treated as one simulated day. CO2 values are
reported by MATSim in grams. The primary map metric is the expanded daily
total in tonnes/day:

    t/day = grams/day * sample expansion factor / 1e6

The event XML files are parsed incrementally so the large .xml.gz files are not
loaded into memory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
import struct
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_EMISSION_EVENTS_DIR = PROJECT_ROOT / "data" / "MATSim" / "emission_events"
DEFAULT_FSA_FILE = PROJECT_ROOT / "data" / "FSA" / "agent_id_fsa_table.csv"
DEFAULT_FSA_SHAPEFILE = PROJECT_ROOT / "data" / "FSA" / "quebec_fsa" / "quebec_fsa.shp"
OUTPUT_DIR = SCRIPT_DIR / "results"

GRAMS_PER_KT = 1_000_000_000
DAYS_PER_YEAR = 365
SAMPLE_EXPANSION_FACTOR = 10
PADDING_RATIO = 0.08
URBAN_PADDING_RATIO = 0.10
URBAN_RIGHT_CROP_RATIO = -0.12
MAP_EXTENT_SCALE = 1.50
MAP_IMAGE_WIDTH = 1000
MAP_IMAGE_HEIGHT = 900
DRAW_TITLE = False
DRAW_LEGEND = True
COLOR_GAMMA = 0.55
CO2_MAP_VALUE_COLUMN = "co2_t_per_day"
CO2_MAP_UNIT_LABEL = "t/day"
NO_DATA_FILL = (238, 238, 238)
NO_DATA_HATCH = (178, 178, 178)
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


def read_fsa_csv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []

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
            fsa = (row.get(fsa_column) or "").strip().upper()
            if agent_id:
                result[agent_id] = fsa or "UNKNOWN"
    return result


def infer_year_scenario(path: Path) -> tuple[str, str]:
    # Expected file name:
    # emission.events.offline.2035.acc_adopt.xml.gz
    name = path.name
    for suffix in (".xml.gz", ".xml"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    parts = name.split(".")
    if len(parts) >= 5 and parts[-2].isdigit():
        return parts[-2], parts[-1]
    return "unknown", path.stem


def summarize_emission_events(
    path: Path,
    fsa_by_agent: dict[str, str],
) -> tuple[dict[str, float], dict[str, float], dict[str, str], int, int]:
    co2_by_agent: dict[str, float] = defaultdict(float)
    co2_by_fsa: dict[str, float] = defaultdict(float)
    agent_by_vehicle: dict[str, str] = {}
    emission_events = 0
    unmatched_emission_events = 0

    with open_text(path) as stream:
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
            elif event_type in {"warmEmissionEvent", "coldEmissionEvent"}:
                vehicle = elem.get("vehicleId") or elem.get("vehicle")
                co2 = elem.get("CO2")
                if vehicle and co2 is not None:
                    emission_events += 1
                    agent_id = agent_by_vehicle.get(vehicle, vehicle)
                    grams = float(co2)
                    co2_by_agent[agent_id] += grams
                    fsa = fsa_by_agent.get(agent_id)
                    if fsa is None:
                        unmatched_emission_events += 1
                        fsa = "UNKNOWN"
                    co2_by_fsa[fsa] += grams
            elem.clear()

    return (
        dict(co2_by_agent),
        dict(co2_by_fsa),
        agent_by_vehicle,
        emission_events,
        unmatched_emission_events,
    )


def kt_per_year(grams_per_day: float) -> float:
    return grams_per_day * SAMPLE_EXPANSION_FACTOR * DAYS_PER_YEAR / GRAMS_PER_KT


def expanded_grams_per_day(sample_grams_per_day: float) -> float:
    return sample_grams_per_day * SAMPLE_EXPANSION_FACTOR


def write_agent_csv(
    path: Path,
    year: str,
    scenario: str,
    co2_by_agent: dict[str, float],
    fsa_by_agent: dict[str, str],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "year",
                "scenario",
                "agent_id",
                "fsa",
                "co2_g_per_day",
                "co2_kg_per_day",
                "co2_kt_per_year",
            ]
        )
        for agent_id in sorted(co2_by_agent):
            grams = co2_by_agent[agent_id]
            expanded_grams = expanded_grams_per_day(grams)
            writer.writerow(
                [
                    year,
                    scenario,
                    agent_id,
                    fsa_by_agent.get(agent_id, "UNKNOWN"),
                    f"{expanded_grams:.6f}",
                    f"{expanded_grams / 1000:.9f}",
                    f"{kt_per_year(grams):.12f}",
                ]
            )


def write_fsa_csv(
    path: Path,
    year: str,
    scenario: str,
    co2_by_fsa: dict[str, float],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "year",
                "scenario",
                "fsa",
                "co2_g_per_day",
                "co2_t_per_day",
                "co2_kt_per_year",
            ]
        )
        for fsa in sorted(co2_by_fsa):
            grams = co2_by_fsa[fsa]
            expanded_grams = expanded_grams_per_day(grams)
            writer.writerow(
                [
                    year,
                    scenario,
                    fsa,
                    f"{expanded_grams:.6f}",
                    f"{expanded_grams / 1_000_000:.9f}",
                    f"{kt_per_year(grams):.12f}",
                ]
            )


def write_combined_fsa_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    fieldnames = [
        "year",
        "scenario",
        "fsa",
        "co2_g_per_day",
        "co2_t_per_day",
        "co2_kt_per_year",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
            if shape_type in {5, 15, 25, 31}:  # Polygon variants.
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
                    points[part_indices[i] : part_indices[i + 1]]
                    for i in range(num_parts)
                ]
                fsa = records[record_index]["CFSAUID"].strip().upper()
                shapes.append(FsaShape(fsa=fsa, parts=parts, bbox=(minx, miny, maxx, maxy)))

            record_index += 1

    return shapes


def color_ramp(value: float, max_value: float) -> tuple[int, int, int]:
    if max_value <= 0 or value <= 0:
        return (255, 253, 240)
    t = min(1.0, max(0.0, value / max_value)) ** COLOR_GAMMA
    stops = [
        (255, 253, 240),
        (255, 239, 171),
        (255, 213, 97),
        (254, 178, 76),
        (240, 96, 35),
        (189, 0, 38),
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


def bounds_for_shapes(
    shapes: list[FsaShape],
    values: dict[str, float],
    crop_to_urban: bool,
) -> tuple[float, float, float, float]:
    if crop_to_urban:
        selected = [shape for shape in shapes if shape.fsa in URBAN_FOCUS_FSA_CODES]
        padding_ratio = URBAN_PADDING_RATIO
    else:
        selected = [shape for shape in shapes if shape.fsa in values]
        padding_ratio = PADDING_RATIO

    if not selected:
        selected = [shape for shape in shapes if shape.fsa in values]
        padding_ratio = PADDING_RATIO
    if not selected:
        raise ValueError("No FSA polygons matched the CO2 summary.")

    minx = min(shape.bbox[0] for shape in selected)
    miny = min(shape.bbox[1] for shape in selected)
    maxx = max(shape.bbox[2] for shape in selected)
    maxy = max(shape.bbox[3] for shape in selected)
    dx = maxx - minx
    dy = maxy - miny
    if crop_to_urban:
        maxx -= dx * URBAN_RIGHT_CROP_RATIO
    minx = minx - dx * padding_ratio
    miny = miny - dy * padding_ratio
    maxx = maxx + dx * padding_ratio
    maxy = maxy + dy * padding_ratio

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


def max_co2_value(csv_paths: Iterable[Path], value_column: str = CO2_MAP_VALUE_COLUMN) -> float:
    max_value = 0.0
    for csv_path in csv_paths:
        with csv_path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                if (row.get("fsa") or "").upper() == "UNKNOWN":
                    continue
                max_value = max(max_value, float(row[value_column]))
    return max_value


def max_co2_kt_per_year(csv_paths: Iterable[Path]) -> float:
    return max_co2_value(csv_paths, "co2_kt_per_year")


def plot_fsa_heatmap(
    csv_path: Path,
    shapefile_path: Path,
    output_path: Path,
    year: str,
    scenario: str,
    shared_max_value: float | None = None,
    crop_to_urban: bool = True,
    value_column: str = CO2_MAP_VALUE_COLUMN,
    unit_label: str = CO2_MAP_UNIT_LABEL,
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Plotting requires Pillow.") from exc

    values: dict[str, float] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row["fsa"] or "").upper()
            if fsa and fsa != "UNKNOWN":
                values[fsa] = float(row[value_column])

    shapes = read_fsa_shapes(shapefile_path)
    shapes_with_data = [shape for shape in shapes if shape.fsa in values]
    if not shapes_with_data:
        raise ValueError("No FSA polygons matched the CO2 summary.")

    minx, miny, maxx, maxy = bounds_for_shapes(shapes, values, crop_to_urban)

    width, height = MAP_IMAGE_WIDTH, MAP_IMAGE_HEIGHT
    legend_width = 220 if DRAW_LEGEND else 0
    margin = 0
    title_height = 90 if DRAW_TITLE else 0
    map_width = width - legend_width - margin * 2
    map_height = height - title_height - margin * 2
    scale = min(map_width / (maxx - minx), map_height / (maxy - miny))
    x_offset = margin + (map_width - (maxx - minx) * scale) / 2
    y_offset = title_height + (map_height - (maxy - miny) * scale) / 2

    def transform(point: tuple[float, float]) -> tuple[int, int]:
        x, y = point
        px = x_offset + (x - minx) * scale
        py = y_offset + (maxy - y) * scale
        return (round(px), round(py))

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    hatch_pattern = Image.new("RGB", (width, height), NO_DATA_FILL)
    hatch_draw = ImageDraw.Draw(hatch_pattern)
    hatch_spacing = 12
    for offset in range(-height, width + height, hatch_spacing):
        hatch_draw.line(
            [(offset, height), (offset + height, 0)],
            fill=NO_DATA_HATCH,
            width=2,
        )

    def draw_hatched_polygon(polygon: list[tuple[int, int]]) -> None:
        if len(polygon) < 3:
            return
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon(polygon, fill=255)
        image.paste(hatch_pattern, (0, 0), mask)
        draw.polygon(polygon, fill=None, outline=(130, 130, 130))

    max_value = shared_max_value if shared_max_value is not None else max(values.values()) if values else 0.0
    tick_values = nice_ticks(max_value)
    vmax = tick_values[-1]

    for shape in shapes:
        shape_minx, shape_miny, shape_maxx, shape_maxy = shape.bbox
        if shape_maxx < minx or shape_minx > maxx or shape_maxy < miny or shape_miny > maxy:
            continue
        value = values.get(shape.fsa)
        for part in shape.parts:
            polygon = [transform(point) for point in part]
            if len(polygon) < 3:
                continue
            if value is None:
                draw_hatched_polygon(polygon)
            else:
                draw.polygon(
                    polygon,
                    fill=color_ramp(value, vmax),
                    outline=(255, 255, 255),
                )

    if DRAW_LEGEND:
        font = ImageFont.load_default()
        label_font = ImageFont.load_default(size=16)
        draw.rectangle([width - legend_width, 0, width, height], fill="white")
        legend_x = width - legend_width + 38
        legend_y = title_height + 90
        legend_h = min(760, height - legend_y - 80)
        legend_w = 36
        for i in range(legend_h):
            frac = 1 - i / max(1, legend_h - 1)
            color = color_ramp(frac * vmax, vmax)
            draw.rectangle(
                [legend_x, legend_y + i, legend_x + legend_w, legend_y + i],
                fill=color,
            )
        draw.rectangle(
            [legend_x, legend_y, legend_x + legend_w, legend_y + legend_h],
            outline=(90, 90, 90),
        )
        draw.text((legend_x, legend_y - 32), unit_label, fill=(30, 30, 30), font=label_font)
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

    if DRAW_TITLE:
        title_font = ImageFont.load_default(size=28)
        label_font = ImageFont.load_default(size=16)
        draw.rectangle([0, 0, width, title_height], fill="white")
        draw.text(
            (60, 28),
            f"CO2 Emissions by FSA - {year} {scenario}",
            fill=(25, 25, 25),
            font=title_font,
        )
        draw.text(
            (60, 64),
            f"Unit: {unit_label}, converted from one simulated day of MATSim CO2 grams",
            fill=(80, 80, 80),
            font=label_font,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def emission_event_files(events_dir: Path, only: list[Path] | None) -> list[Path]:
    if only:
        return [path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve() for path in only]
    return sorted(events_dir.glob("emission.events.offline.*.xml.gz"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize MATSim CO2 emission events by FSA and draw heatmaps."
    )
    parser.add_argument("--events-dir", type=Path, default=DEFAULT_EMISSION_EVENTS_DIR)
    parser.add_argument("--fsa-file", type=Path, default=DEFAULT_FSA_FILE)
    parser.add_argument("--shapefile", type=Path, default=DEFAULT_FSA_SHAPEFILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--event-file",
        type=Path,
        action="append",
        help="Process a specific emission event file. Can be supplied more than once.",
    )
    parser.add_argument(
        "--no-agent-csv",
        action="store_true",
        help="Skip per-agent CSV output.",
    )
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Regenerate heatmaps from existing per-FSA CSV outputs.",
    )
    parser.add_argument(
        "--full-extent",
        action="store_true",
        help="Plot the full FSA extent instead of the central urban crop.",
    )
    parser.add_argument(
        "--legend-max",
        type=float,
        help="Use an explicit t/day maximum for all heatmap legends.",
    )
    return parser.parse_args()


def validate_inputs(args: argparse.Namespace, files: list[Path]) -> None:
    missing = [path for path in [args.fsa_file, args.shapefile] if not path.is_file()]
    missing.extend(path for path in files if not path.is_file())
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Input file(s) not found:\n{formatted}")
    if not files:
        raise FileNotFoundError(f"No emission event files found in {args.events_dir}")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    files = emission_event_files(args.events_dir, args.event_file)
    validate_inputs(args, files)

    fsa_by_agent = read_fsa_csv(args.fsa_file)
    combined_rows: list[dict[str, str]] = []
    map_jobs: list[tuple[Path, Path, str, str]] = []

    for event_file in files:
        year, scenario = infer_year_scenario(event_file)
        fsa_output = args.output_dir / f"co2_emissions_by_fsa_{year}_{scenario}.csv"
        agent_output = args.output_dir / f"co2_emissions_by_agent_{year}_{scenario}.csv"
        map_output = args.output_dir / f"co2_emissions_by_fsa_{year}_{scenario}.png"
        map_jobs.append((fsa_output, map_output, year, scenario))

        if args.plot_only:
            continue

        print(f"Streaming {event_file.name}...", file=sys.stderr)
        co2_by_agent, co2_by_fsa, agent_by_vehicle, events, unmatched = (
            summarize_emission_events(event_file, fsa_by_agent)
        )

        if not args.no_agent_csv:
            write_agent_csv(agent_output, year, scenario, co2_by_agent, fsa_by_agent)
        write_fsa_csv(fsa_output, year, scenario, co2_by_fsa)

        with fsa_output.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            combined_rows.extend(reader)

        print(
            f"  emission events: {events:,}; vehicle-agent mappings: "
            f"{len(agent_by_vehicle):,}; unmatched emission events: {unmatched:,}",
            file=sys.stderr,
        )
        print(f"  wrote {fsa_output}", file=sys.stderr)
        if not args.no_agent_csv:
            print(f"  wrote {agent_output}", file=sys.stderr)

    if combined_rows and len(files) > 1 and not args.plot_only:
        combined_output = args.output_dir / "co2_emissions_by_fsa_all_scenarios.csv"
        write_combined_fsa_csv(combined_output, combined_rows)
        print(f"Wrote {combined_output}", file=sys.stderr)

    shared_max_value = args.legend_max
    if shared_max_value is None:
        shared_max_value = max_co2_value(job[0] for job in map_jobs)
    shared_vmax = nice_ticks(shared_max_value)[-1]
    print(f"Using shared heatmap legend max: {shared_vmax:g} {CO2_MAP_UNIT_LABEL}", file=sys.stderr)

    for fsa_output, map_output, year, scenario in map_jobs:
        print(f"Plotting {map_output}", file=sys.stderr)
        plot_fsa_heatmap(
            fsa_output,
            args.shapefile,
            map_output,
            year,
            scenario,
            shared_max_value=shared_max_value,
            crop_to_urban=not args.full_extent,
        )
        print(f"  wrote {map_output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
