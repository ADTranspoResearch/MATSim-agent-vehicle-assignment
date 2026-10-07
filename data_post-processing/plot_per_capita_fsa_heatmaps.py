#!/usr/bin/env python3
"""Create per-capita FSA heatmaps from existing annual FSA summaries."""

from __future__ import annotations

import csv
import importlib.util
import math
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = SCRIPT_DIR / "results"
FSA_FILE = PROJECT_ROOT / "data" / "FSA" / "agent_id_fsa_table.csv"
FSA_SHAPEFILE = PROJECT_ROOT / "data" / "FSA" / "quebec_fsa" / "quebec_fsa.shp"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


co2_map = load_module("co2_map", SCRIPT_DIR / "summarize_fsa_co2_emissions.py")
ev_map = load_module("ev_map", SCRIPT_DIR / "summarize_ev_electricity_by_scenario.py")

CO2_2020_STOPS = [
    (255, 255, 217),
    (255, 238, 150),
    (254, 204, 92),
    (253, 141, 60),
    (204, 76, 2),
]
CO2_2035_STOPS = CO2_2020_STOPS
EV_2020_STOPS = [
    (247, 252, 245),
    (229, 245, 224),
    (199, 233, 192),
    (161, 217, 155),
    (65, 171, 93),
]
EV_2035_STOPS = [
    (237, 248, 233),
    (186, 228, 179),
    (116, 196, 118),
    (49, 163, 84),
    (0, 109, 44),
]


def read_fsa_population(path: Path, sample_expansion_factor: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        fsa_column = "fsa" if "fsa" in fieldnames else "CFSAUID"
        for row in reader:
            fsa = (row.get(fsa_column) or "").strip().upper()
            if fsa:
                counts[fsa] = counts.get(fsa, 0) + 1
    return {fsa: count * sample_expansion_factor for fsa, count in counts.items()}


def per_capita_output_path(source_path: Path, metric: str) -> Path:
    stem = source_path.stem
    if metric == "co2":
        stem = stem.replace("co2_emissions_by_fsa", "co2_emissions_per_capita_by_fsa")
    else:
        stem = stem.replace("ev_electricity_by_fsa", "ev_electricity_per_capita_by_fsa")
    return source_path.with_name(f"{stem}.csv")


def write_per_capita_csv(
    source_path: Path,
    output_path: Path,
    population_by_fsa: dict[str, int],
    total_column: str,
    per_capita_column: str,
    multiplier: float,
) -> float:
    max_value = 0.0
    with source_path.open("r", encoding="utf-8", newline="") as src, output_path.open(
        "w", encoding="utf-8", newline=""
    ) as dst:
        reader = csv.DictReader(src)
        fieldnames = ["year", "scenario", "fsa", "population", total_column, per_capita_column]
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            fsa = (row["fsa"] or "").upper()
            population = population_by_fsa.get(fsa, 0)
            total = float(row[total_column])
            per_capita = total * multiplier / population if population > 0 else 0.0
            writer.writerow(
                {
                    "year": row["year"],
                    "scenario": row["scenario"],
                    "fsa": fsa,
                    "population": population,
                    total_column: f"{total:.12f}",
                    per_capita_column: f"{per_capita:.6f}",
                }
            )
            if fsa != "UNKNOWN":
                max_value = max(max_value, per_capita)
    return max_value


def read_values(path: Path, value_column: str) -> dict[str, float]:
    values = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row["fsa"] or "").upper()
            if fsa and fsa != "UNKNOWN":
                values[fsa] = float(row[value_column])
    return values


def format_tick(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def color_ramp(
    value: float,
    max_value: float,
    stops: list[tuple[int, int, int]],
    gamma: float = 0.55,
) -> tuple[int, int, int]:
    if max_value <= 0 or value <= 0:
        return stops[0]
    t = min(1.0, max(0.0, value / max_value)) ** gamma
    scaled = t * (len(stops) - 1)
    idx = min(len(stops) - 2, int(math.floor(scaled)))
    frac = scaled - idx
    a = stops[idx]
    b = stops[idx + 1]
    return tuple(round(a[i] + (b[i] - a[i]) * frac) for i in range(3))


def draw_per_capita_heatmap(
    csv_path: Path,
    output_path: Path,
    value_column: str,
    legend_label: str,
    shared_max_value: float,
    stops: list[tuple[int, int, int]],
    use_nice_scale: bool = True,
    gamma: float = 0.55,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    values = read_values(csv_path, value_column)
    shapes = co2_map.read_fsa_shapes(FSA_SHAPEFILE)
    minx, miny, maxx, maxy = co2_map.bounds_for_shapes(shapes, values, True)

    width, height = co2_map.MAP_IMAGE_WIDTH, co2_map.MAP_IMAGE_HEIGHT
    legend_width = 220 if co2_map.DRAW_LEGEND else 0
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
    tick_values = (
        co2_map.nice_ticks(shared_max_value)
        if use_nice_scale
        else [shared_max_value * i / 4 for i in range(5)]
    )
    vmax = tick_values[-1]

    for shape in shapes:
        value = values.get(shape.fsa)
        fill = color_ramp(value or 0.0, vmax, stops, gamma) if value is not None else (235, 235, 235)
        outline = (255, 255, 255) if value is not None else (210, 210, 210)
        for part in shape.parts:
            polygon = [transform(point) for point in part]
            if len(polygon) >= 3:
                draw.polygon(polygon, fill=fill, outline=outline)

    if co2_map.DRAW_LEGEND:
        font = ImageFont.load_default()
        label_font = ImageFont.load_default(size=14)
        legend_x = width - legend_width + 38
        legend_y = 90
        legend_h = min(760, height - legend_y - 80)
        legend_w = 36
        draw.rectangle([width - legend_width, 0, width, height], fill="white")
        for i in range(legend_h):
            frac = 1 - i / max(1, legend_h - 1)
            draw.rectangle(
                [legend_x, legend_y + i, legend_x + legend_w, legend_y + i],
                fill=color_ramp(frac * vmax, vmax, stops, gamma),
            )
        draw.rectangle(
            [legend_x, legend_y, legend_x + legend_w, legend_y + legend_h],
            outline=(90, 90, 90),
        )
        draw.text((legend_x, legend_y - 34), legend_label, fill=(30, 30, 30), font=label_font)
        for tick in tick_values:
            y = legend_y + legend_h - (tick / vmax * legend_h if vmax else 0)
            draw.line([legend_x + legend_w, y, legend_x + legend_w + 8, y], fill=(60, 60, 60))
            draw.text(
                (legend_x + legend_w + 14, y),
                format_tick(tick),
                anchor="lm",
                fill=(50, 50, 50),
                font=font,
            )

    image.save(output_path)


def build_metric(
    source_paths: list[Path],
    metric: str,
    total_column: str,
    per_capita_column: str,
    multiplier: float,
    legend_label: str,
    stops_2020: list[tuple[int, int, int]],
    stops_2035: list[tuple[int, int, int]],
    population_by_fsa: dict[str, int],
) -> list[Path]:
    per_capita_paths = []
    for source_path in source_paths:
        output_path = per_capita_output_path(source_path, metric)
        write_per_capita_csv(
            source_path,
            output_path,
            population_by_fsa,
            total_column,
            per_capita_column,
            multiplier,
        )
        per_capita_paths.append(output_path)

    max_2020 = grouped_max(
        [path for path in per_capita_paths if "_2020_" in path.name],
        per_capita_column,
        use_nice_max=metric not in {"co2", "ev"},
    )
    max_2035 = grouped_max(
        [path for path in per_capita_paths if "_2035_" in path.name],
        per_capita_column,
        use_nice_max=metric not in {"co2", "ev"},
    )
    if metric == "co2":
        max_2035 = 3800
    for csv_path in per_capita_paths:
        png_path = csv_path.with_suffix(".png")
        is_2020 = "_2020_" in csv_path.name
        draw_per_capita_heatmap(
            csv_path,
            png_path,
            per_capita_column,
            legend_label,
            max_2020 if is_2020 else max_2035,
            stops_2020 if is_2020 else stops_2035,
            use_nice_scale=metric not in {"co2", "ev"},
            gamma=(
                1.1
                if metric == "co2" and is_2020
                else 0.61
                if metric == "co2"
                else 0.50
                if is_2020
                else 0.61
            ),
        )
    return per_capita_paths


def grouped_max(paths: list[Path], value_column: str, use_nice_max: bool = True) -> float:
    max_value = 0.0
    for path in paths:
        values = read_values(path, value_column)
        if values:
            max_value = max(max_value, max(values.values()))
    if use_nice_max:
        return co2_map.nice_ticks(max_value)[-1]
    return math.ceil(max_value / 100) * 100


def main() -> int:
    population_by_fsa = read_fsa_population(FSA_FILE, co2_map.SAMPLE_EXPANSION_FACTOR)

    co2_paths = sorted(RESULTS_DIR.glob("co2_emissions_by_fsa_*.csv"))
    co2_paths = [path for path in co2_paths if path.name != "co2_emissions_by_fsa_all_scenarios.csv"]
    ev_paths = sorted(RESULTS_DIR.glob("ev_electricity_by_fsa_*.csv"))

    co2_outputs = build_metric(
        co2_paths,
        "co2",
        "co2_kt_per_year",
        "co2_kg_per_person_year",
        1_000_000.0,
        "kg CO2/person/year",
        CO2_2020_STOPS,
        CO2_2035_STOPS,
        population_by_fsa,
    )
    ev_outputs = build_metric(
        ev_paths,
        "ev",
        "electricity_gwh_per_year",
        "electricity_kwh_per_person_year",
        1_000_000.0,
        "kWh/person/year",
        EV_2020_STOPS,
        EV_2035_STOPS,
        population_by_fsa,
    )

    for path in co2_outputs + ev_outputs:
        print(f"Wrote {path}")
        print(f"Wrote {path.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
