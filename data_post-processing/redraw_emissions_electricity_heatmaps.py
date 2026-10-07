#!/usr/bin/env python3
"""Redraw CO2 and EV electricity FSA heatmaps with grouped colors and top labels."""

from __future__ import annotations

import csv
import importlib.util
import math
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = SCRIPT_DIR / "results"
FSA_SHAPEFILE = PROJECT_ROOT / "data" / "FSA" / "quebec_fsa" / "quebec_fsa.shp"

SCENARIOS = [
    ("2020", "REF"),
    ("2035", "BAU"),
    ("2035", "DELAYED_ADOPTION"),
    ("2035", "POLICY_ALIGNED"),
    ("2035", "ACCELERATED_ADOPTION"),
]

CO2_2020_STOPS = [
    (255, 255, 217),
    (255, 238, 150),
    (254, 204, 92),
    (253, 141, 60),
    (204, 76, 2),
]
CO2_2035_STOPS = [
    (255, 245, 235),
    (254, 216, 190),
    (253, 174, 107),
    (252, 120, 75),
    (222, 45, 38),
    (165, 15, 21),
]
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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


co2_map = load_module("co2_map_for_redraw", SCRIPT_DIR / "summarize_fsa_co2_emissions.py")
ev_map = load_module("ev_map_for_redraw", SCRIPT_DIR / "summarize_ev_electricity_by_scenario.py")


def read_values(path: Path, value_column: str) -> dict[str, float]:
    values = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row["fsa"] or "").upper()
            if fsa and fsa != "UNKNOWN":
                values[fsa] = float(row[value_column])
    return values


def color_ramp(value: float, max_value: float, stops: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if max_value <= 0 or value <= 0:
        return stops[0]
    t = min(1.0, max(0.0, value / max_value)) ** 0.55
    scaled = t * (len(stops) - 1)
    idx = min(len(stops) - 2, int(math.floor(scaled)))
    frac = scaled - idx
    a = stops[idx]
    b = stops[idx + 1]
    return tuple(round(a[i] + (b[i] - a[i]) * frac) for i in range(3))


def format_tick(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    if len(points) < 3:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    area = 0.0
    cx = 0.0
    cy = 0.0
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[(i + 1) % len(points)]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area) < 1e-12:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    area *= 0.5
    return (cx / (6 * area), cy / (6 * area))


def representative_point(shape) -> tuple[float, float]:
    largest_part = max(shape.parts, key=lambda part: abs(part_area(part)) if len(part) >= 3 else 0)
    return polygon_centroid(largest_part)


def part_area(points: list[tuple[float, float]]) -> float:
    area = 0.0
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[(i + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return area / 2


def draw_top_labels(draw, shapes_by_fsa, values, transform, font, map_width: int, height: int) -> None:
    top_items = sorted(values.items(), key=lambda item: item[1], reverse=True)[:5]
    for rank, (fsa, value) in enumerate(top_items, 1):
        shape = shapes_by_fsa.get(fsa)
        if shape is None:
            continue
        x, y = transform(representative_point(shape))
        x = max(42, min(map_width - 42, x))
        y = max(24, min(height - 24, y))
        text = f"{rank}. {fsa}\n{format_tick(value)}"
        bbox = draw.multiline_textbbox((x, y), text, anchor="mm", font=font, spacing=2)
        pad = 3
        draw.rounded_rectangle(
            [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
            radius=3,
            fill=(255, 255, 255),
            outline=(40, 40, 40),
            width=1,
        )
        draw.multiline_text((x, y), text, anchor="mm", fill=(20, 20, 20), font=font, spacing=2)


def draw_heatmap(
    csv_path: Path,
    output_path: Path,
    value_column: str,
    legend_label: str,
    max_value: float,
    stops: list[tuple[int, int, int]],
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    values = read_values(csv_path, value_column)
    shapes = co2_map.read_fsa_shapes(FSA_SHAPEFILE)
    shapes_by_fsa = {shape.fsa: shape for shape in shapes}
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
    tick_values = co2_map.nice_ticks(max_value)
    vmax = tick_values[-1]

    for shape in shapes:
        value = values.get(shape.fsa)
        fill = color_ramp(value or 0.0, vmax, stops) if value is not None else (235, 235, 235)
        outline = (255, 255, 255) if value is not None else (210, 210, 210)
        for part in shape.parts:
            polygon = [transform(point) for point in part]
            if len(polygon) >= 3:
                draw.polygon(polygon, fill=fill, outline=outline)

    font = ImageFont.load_default()
    label_font = ImageFont.load_default(size=14)
    top_font = ImageFont.load_default(size=12)
    # Top labels are intentionally omitted for the publication heatmap version.

    if co2_map.DRAW_LEGEND:
        draw.rectangle([width - legend_width, 0, width, height], fill="white")
        legend_x = width - legend_width + 38
        legend_y = 90
        legend_h = min(760, height - legend_y - 80)
        legend_w = 36
        for i in range(legend_h):
            frac = 1 - i / max(1, legend_h - 1)
            draw.rectangle(
                [legend_x, legend_y + i, legend_x + legend_w, legend_y + i],
                fill=color_ramp(frac * vmax, vmax, stops),
            )
        draw.rectangle(
            [legend_x, legend_y, legend_x + legend_w, legend_y + legend_h],
            outline=(90, 90, 90),
        )
        draw.text((legend_x, legend_y - 32), legend_label, fill=(30, 30, 30), font=label_font)
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


def grouped_max(paths: list[Path], value_column: str) -> float:
    max_value = 0.0
    for path in paths:
        values = read_values(path, value_column)
        if values:
            max_value = max(max_value, max(values.values()))
    return max_value


def redraw_metric(
    prefix: str,
    value_column: str,
    legend_label: str,
    stops_2020: list[tuple[int, int, int]],
    stops_2035: list[tuple[int, int, int]],
) -> None:
    paths = {
        (year, scenario): RESULTS_DIR / f"{prefix}_{year}_{scenario}.csv"
        for year, scenario in SCENARIOS
    }
    max_2020 = grouped_max([paths[("2020", "REF")]], value_column)
    max_2035 = grouped_max(
        [path for (year, _), path in paths.items() if year == "2035"], value_column
    )
    for year, scenario in SCENARIOS:
        csv_path = paths[(year, scenario)]
        png_path = csv_path.with_suffix(".png")
        draw_heatmap(
            csv_path,
            png_path,
            value_column,
            legend_label,
            max_2020 if year == "2020" else max_2035,
            stops_2020 if year == "2020" else stops_2035,
        )
        print(f"Wrote {png_path}")


def main() -> int:
    redraw_metric(
        "co2_emissions_by_fsa",
        "co2_kt_per_year",
        "kt/year",
        CO2_2035_STOPS,
        CO2_2020_STOPS,
    )
    redraw_metric(
        "ev_electricity_by_fsa",
        "electricity_gwh_per_year",
        "GWh/year",
        EV_2020_STOPS,
        EV_2035_STOPS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
