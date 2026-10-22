#!/usr/bin/env python3
"""
Create a bar chart comparing annual total CO2 emissions against the REF case.
"""

from __future__ import annotations

import csv
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
INPUT_CSV = RESULTS_DIR / "co2_emissions_by_fsa_all_scenarios.csv"
OUTPUT_CSV = RESULTS_DIR / "total_co2_scenario_comparison.csv"
OUTPUT_PNG = RESULTS_DIR / "total_co2_scenario_comparison.png"

SCENARIO_ORDER = [
    ("2020", "REF", "2020 REF"),
    ("2035", "bau", "2035 bau"),
    ("2035", "del_adopt", "2035 Delayed"),
    ("2035", "pol_align", "2035 Policy-aligned"),
    ("2035", "acc_adopt", "2035 Accelerated"),
]


def read_totals(path: Path) -> dict[tuple[str, str], float]:
    totals: dict[tuple[str, str], float] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            key = (row["year"], row["scenario"])
            totals[key] = totals.get(key, 0.0) + float(row["co2_kt_per_year"])
    return totals


def write_comparison_csv(
    path: Path,
    rows: list[tuple[str, str, str, float, float, float]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "year",
                "scenario",
                "label",
                "total_co2_kt_per_year",
                "reduction_vs_2020_ref_kt_per_year",
                "reduction_vs_2020_ref_percent",
            ]
        )
        for year, scenario, label, total, reduction_kt, reduction_percent in rows:
            writer.writerow(
                [
                    year,
                    scenario,
                    label,
                    f"{total:.6f}",
                    f"{reduction_kt:.6f}",
                    f"{reduction_percent:.2f}",
                ]
            )


def draw_bar_chart(
    path: Path,
    rows: list[tuple[str, str, str, float, float, float]],
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Plotting requires Pillow.") from exc

    width, height = 1600, 1000
    margin_left = 130
    margin_right = 70
    margin_top = 70
    margin_bottom = 190
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    axis_font = ImageFont.load_default(size=19)
    label_font = ImageFont.load_default(size=22)
    small_font = ImageFont.load_default(size=17)
    annotation_font = ImageFont.load_default(size=18)

    max_value = max(row[3] for row in rows)
    y_max = 100.0
    if max_value > y_max:
        y_max = ((int(max_value) // 100) + 1) * 100

    def y_for(value: float) -> float:
        return margin_top + plot_height - (value / y_max) * plot_height

    colors = {
        "REF": (220, 74, 35),
        "bau": (244, 151, 52),
        "del_adopt": (246, 180, 76),
        "pol_align": (251, 202, 93),
        "acc_adopt": (255, 223, 130),
    }
    annotation_color = (35, 125, 68)

    def draw_dashed_rectangle(
        xy: tuple[float, float, float, float],
        color: tuple[int, int, int],
        width_px: int = 3,
        dash: int = 12,
        gap: int = 7,
    ) -> None:
        x0, y0, x1, y1 = xy
        x = x0
        while x < x1:
            draw.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width_px)
            draw.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width_px)
            x += dash + gap
        y = y0
        while y < y1:
            draw.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width_px)
            draw.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width_px)
            y += dash + gap

    axis_color = (65, 65, 65)
    grid_color = (225, 225, 225)
    draw.line(
        [
            (margin_left, margin_top),
            (margin_left, margin_top + plot_height),
            (margin_left + plot_width, margin_top + plot_height),
        ],
        fill=axis_color,
        width=2,
    )

    tick_step = 20 if y_max <= 100 else 100
    for tick in range(0, int(y_max) + 1, tick_step):
        y = y_for(tick)
        draw.line([(margin_left - 8, y), (margin_left, y)], fill=axis_color, width=2)
        draw.line([(margin_left, y), (margin_left + plot_width, y)], fill=grid_color)
        draw.text(
            (margin_left - 18, y),
            f"{tick}",
            fill=(45, 45, 45),
            anchor="rm",
            font=small_font,
        )

    draw.text(
        (36, margin_top + plot_height / 2),
        "kt/year",
        fill=(45, 45, 45),
        anchor="mm",
        font=axis_font,
    )

    bar_count = len(rows)
    slot_width = plot_width / bar_count
    bar_width = slot_width * 0.58
    bar_geometries = []

    for idx, (_, scenario, label, total, reduction_kt, reduction_percent) in enumerate(rows):
        center_x = margin_left + slot_width * (idx + 0.5)
        x0 = center_x - bar_width / 2
        x1 = center_x + bar_width / 2
        y0 = y_for(total)
        y1 = margin_top + plot_height
        color = colors.get(scenario, (245, 180, 80))
        draw.rectangle([x0, y0, x1, y1], fill=color, outline=(255, 255, 255), width=2)
        bar_geometries.append(
            (center_x, bar_width, y0, y1, scenario, label, total, reduction_kt, reduction_percent)
        )

    for center_x, bar_width, y0, _, scenario, _, _, reduction_kt, reduction_percent in bar_geometries:
        if scenario != "REF":
            box_width = bar_width * 1.18
            box_height = 64
            box_bottom = y0 - 10
            box_top = box_bottom - box_height
            box_left = center_x - box_width / 2
            box_right = center_x + box_width / 2
            draw.rounded_rectangle(
                [box_left, box_top, box_right, box_bottom],
                radius=8,
                fill=(248, 255, 249),
            )
            draw_dashed_rectangle(
                (box_left, box_top, box_right, box_bottom),
                annotation_color,
            )
            draw.text(
                (center_x, box_top + 22),
                f"-{reduction_kt:.1f} kt/year",
                fill=annotation_color,
                anchor="mm",
                font=annotation_font,
            )
            draw.text(
                (center_x, box_top + 46),
                f"{reduction_percent:.1f}% reduction",
                fill=annotation_color,
                anchor="mm",
                font=annotation_font,
            )

    for center_x, _, y0, y1, scenario, label, total, _, _ in bar_geometries:
        total_label_y = y0 - 35 if scenario == "REF" else y0 - 96
        draw.text(
            (center_x, total_label_y),
            f"{total:.1f}",
            fill=(25, 25, 25),
            anchor="mm",
            font=label_font,
        )
        if scenario == "REF":
            draw.text(
                (center_x, y0 - 10),
                "baseline",
                fill=(80, 80, 80),
                anchor="mm",
                font=small_font,
            )
        else:
            pass

        words = label.split()
        if len(words) >= 3:
            x_label = f"{words[0]} {words[1]}\n{' '.join(words[2:])}"
        else:
            x_label = label
        label_y = y1 + 24
        for line in x_label.split("\n"):
            draw.text((center_x, label_y), line, fill=(35, 35, 35), anchor="mm", font=axis_font)
            label_y += 24

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    totals = read_totals(INPUT_CSV)
    ref_total = totals[("2020", "REF")]

    rows = []
    for year, scenario, label in SCENARIO_ORDER:
        total = totals[(year, scenario)]
        reduction_kt = ref_total - total
        reduction_percent = (1 - total / ref_total) * 100
        rows.append((year, scenario, label, total, reduction_kt, reduction_percent))

    write_comparison_csv(OUTPUT_CSV, rows)
    draw_bar_chart(OUTPUT_PNG, rows)
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
