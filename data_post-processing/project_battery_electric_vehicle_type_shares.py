#!/usr/bin/env python3
"""
Project Quebec battery-electric vehicle type shares to 2035.

The projection uses a simple stock-flow extrapolation: average annual net
additions by vehicle type from 2022-2024 are added forward to 2035, then the
projected counts are normalized into shares.
"""

from __future__ import annotations

import csv
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
INPUT_CSV = RESULTS_DIR / "battery_electric_vehicle_type_counts_quebec.csv"
OUTPUT_CSV = RESULTS_DIR / "battery_electric_vehicle_type_share_projection_2035.csv"
OUTPUT_PNG = RESULTS_DIR / "battery_electric_vehicle_type_share_projection_2035.png"

BASE_YEAR = 2024
TARGET_YEAR = 2035
TREND_START_YEAR = 2022


def read_counts(path: Path) -> dict[int, dict[str, float]]:
    counts: dict[int, dict[str, float]] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            year = int(row["year"])
            vehicle_type = row["vehicle_type"]
            value = float(row["battery_electric_vehicles"])
            counts.setdefault(year, {})[vehicle_type] = value
    return counts


def project_counts(
    counts: dict[int, dict[str, float]],
) -> list[dict[str, float | str | int]]:
    vehicle_types = list(counts[BASE_YEAR])
    trend_years = list(range(TREND_START_YEAR, BASE_YEAR + 1))
    years_forward = TARGET_YEAR - BASE_YEAR

    rows = []
    for vehicle_type in vehicle_types:
        annual_changes = [
            counts[year][vehicle_type] - counts[year - 1][vehicle_type]
            for year in trend_years
        ]
        avg_annual_change = sum(annual_changes) / len(annual_changes)
        base_count = counts[BASE_YEAR][vehicle_type]
        projected_count = max(0.0, base_count + avg_annual_change * years_forward)
        rows.append(
            {
                "vehicle_type": vehicle_type,
                "base_year": BASE_YEAR,
                "base_count": base_count,
                "avg_annual_change_2022_2024": avg_annual_change,
                "target_year": TARGET_YEAR,
                "projected_count": projected_count,
            }
        )

    total = sum(float(row["projected_count"]) for row in rows)
    for row in rows:
        row["projected_share"] = float(row["projected_count"]) / total
    return rows


def write_projection_csv(path: Path, rows: list[dict[str, float | str | int]]) -> None:
    fieldnames = [
        "vehicle_type",
        "base_year",
        "base_count",
        "avg_annual_change_2022_2024",
        "target_year",
        "projected_count",
        "projected_share",
        "projected_share_percent",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            output = dict(row)
            output["base_count"] = f"{float(row['base_count']):.0f}"
            output["avg_annual_change_2022_2024"] = (
                f"{float(row['avg_annual_change_2022_2024']):.2f}"
            )
            output["projected_count"] = f"{float(row['projected_count']):.0f}"
            output["projected_share"] = f"{float(row['projected_share']):.8f}"
            output["projected_share_percent"] = (
                f"{float(row['projected_share']) * 100:.2f}"
            )
            writer.writerow(output)


def draw_projection_chart(path: Path, rows: list[dict[str, float | str | int]]) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Plotting requires Pillow.") from exc

    rows = sorted(rows, key=lambda row: float(row["projected_share"]), reverse=True)
    width, height = 1500, 900
    margin_left = 390
    margin_right = 110
    margin_top = 110
    margin_bottom = 90
    plot_width = width - margin_left - margin_right
    bar_height = 66
    row_gap = 34

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=34)
    axis_font = ImageFont.load_default(size=18)
    label_font = ImageFont.load_default(size=20)
    small_font = ImageFont.load_default(size=16)

    colors = [
        (224, 126, 38),
        (39, 92, 141),
        (46, 125, 80),
        (151, 72, 143),
        (142, 142, 142),
        (95, 95, 95),
    ]

    draw.text(
        (margin_left, 35),
        "Projected 2035 battery-electric vehicle type shares in Quebec",
        fill=(25, 25, 25),
        font=title_font,
    )
    draw.text(
        (margin_left, 78),
        "Stock-flow extrapolation using average annual net additions from 2022-2024",
        fill=(80, 80, 80),
        font=axis_font,
    )

    x0 = margin_left
    y = margin_top
    for idx, row in enumerate(rows):
        share = float(row["projected_share"])
        count = float(row["projected_count"])
        vehicle_type = str(row["vehicle_type"])
        bar_width = share * plot_width
        color = colors[idx % len(colors)]
        draw.text(
            (x0 - 18, y + bar_height / 2),
            vehicle_type,
            fill=(35, 35, 35),
            anchor="rm",
            font=label_font,
        )
        draw.rectangle(
            [x0, y, x0 + bar_width, y + bar_height],
            fill=color,
            outline=(255, 255, 255),
            width=2,
        )
        draw.text(
            (x0 + bar_width + 16, y + bar_height / 2),
            f"{share * 100:.1f}% ({count:,.0f})",
            fill=color,
            anchor="lm",
            font=label_font,
        )
        y += bar_height + row_gap

    axis_y = height - margin_bottom
    draw.line([(x0, axis_y), (x0 + plot_width, axis_y)], fill=(70, 70, 70), width=2)
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        x = x0 + tick * plot_width
        draw.line([(x, axis_y), (x, axis_y + 8)], fill=(70, 70, 70), width=2)
        draw.text(
            (x, axis_y + 32),
            f"{tick * 100:.0f}%",
            fill=(55, 55, 55),
            anchor="mm",
            font=small_font,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    counts = read_counts(INPUT_CSV)
    rows = project_counts(counts)
    write_projection_csv(OUTPUT_CSV, rows)
    draw_projection_chart(OUTPUT_PNG, rows)
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
