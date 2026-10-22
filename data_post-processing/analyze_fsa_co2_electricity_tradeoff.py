#!/usr/bin/env python3
"""Analyze FSA-level CO2 reduction versus EV electricity demand trade-offs."""

from __future__ import annotations

import csv
import math
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = SCRIPT_DIR / "results"

SCENARIOS = [
    ("2035", "bau", "2035 Business-as-usual"),
    ("2035", "del_adopt", "2035 Delayed adoption"),
    ("2035", "pol_align", "2035 Policy-aligned"),
    ("2035", "acc_adopt", "2035 Accelerated adoption"),
]


def read_metric(path: Path, column: str) -> dict[str, float]:
    values = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row["fsa"] or "").upper()
            if fsa and fsa != "UNKNOWN":
                values[fsa] = float(row[column])
    return values


def read_population(path: Path) -> dict[str, int]:
    values = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            fsa = (row["fsa"] or "").upper()
            if fsa and fsa != "UNKNOWN":
                values[fsa] = int(row["population"])
    return values


def percentile_scores(rows: list[dict], column: str, high_value_good: bool = True) -> dict[str, float]:
    valid = [(row["fsa"], row[column]) for row in rows if row[column] is not None]
    if not valid:
        return {}
    valid.sort(key=lambda item: item[1])
    denominator = max(1, len(valid) - 1)
    scores = {}
    for idx, (fsa, _) in enumerate(valid):
        percentile = idx / denominator
        scores[fsa] = percentile if high_value_good else 1 - percentile
    return scores


def format_number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"


def build_tradeoff_rows() -> list[dict]:
    ref_co2 = read_metric(RESULTS_DIR / "co2_emissions_by_fsa_2020_REF.csv", "co2_kt_per_year")
    ref_electricity = read_metric(
        RESULTS_DIR / "ev_electricity_by_fsa_2020_REF.csv", "electricity_gwh_per_year"
    )
    population = read_population(RESULTS_DIR / "co2_emissions_per_capita_by_fsa_2020_REF.csv")

    all_rows = []
    for year, scenario, label in SCENARIOS:
        scenario_co2 = read_metric(
            RESULTS_DIR / f"co2_emissions_by_fsa_{year}_{scenario}.csv", "co2_kt_per_year"
        )
        scenario_electricity = read_metric(
            RESULTS_DIR / f"ev_electricity_by_fsa_{year}_{scenario}.csv",
            "electricity_gwh_per_year",
        )
        fsas = sorted(set(ref_co2) | set(scenario_co2) | set(ref_electricity) | set(scenario_electricity))
        rows = []
        for fsa in fsas:
            pop = population.get(fsa, 0)
            ref_co2_kt = ref_co2.get(fsa, 0.0)
            scen_co2_kt = scenario_co2.get(fsa, 0.0)
            ref_elec_gwh = ref_electricity.get(fsa, 0.0)
            scen_elec_gwh = scenario_electricity.get(fsa, 0.0)
            co2_reduction_kt = ref_co2_kt - scen_co2_kt
            electricity_increase_gwh = scen_elec_gwh - ref_elec_gwh
            co2_reduction_kg = co2_reduction_kt * 1_000_000
            electricity_increase_kwh = electricity_increase_gwh * 1_000_000
            efficiency = (
                co2_reduction_kg / electricity_increase_kwh
                if electricity_increase_kwh > 0
                else None
            )
            row = {
                "year": year,
                "scenario": scenario,
                "scenario_label": label,
                "fsa": fsa,
                "population": pop,
                "ref_co2_kt_per_year": ref_co2_kt,
                "scenario_co2_kt_per_year": scen_co2_kt,
                "co2_reduction_kt_per_year": co2_reduction_kt,
                "co2_reduction_percent": co2_reduction_kt / ref_co2_kt * 100 if ref_co2_kt > 0 else None,
                "co2_reduction_kg_per_person_year": co2_reduction_kg / pop if pop > 0 else None,
                "ref_electricity_gwh_per_year": ref_elec_gwh,
                "scenario_electricity_gwh_per_year": scen_elec_gwh,
                "electricity_increase_gwh_per_year": electricity_increase_gwh,
                "electricity_increase_kwh_per_person_year": electricity_increase_kwh / pop if pop > 0 else None,
                "kg_co2_reduced_per_kwh": efficiency,
            }
            rows.append(row)

        reduction_pctile = percentile_scores(rows, "co2_reduction_kt_per_year", high_value_good=True)
        electricity_low_pctile = percentile_scores(
            rows, "electricity_increase_gwh_per_year", high_value_good=False
        )
        electricity_high_pctile = percentile_scores(
            rows, "electricity_increase_gwh_per_year", high_value_good=True
        )
        efficiency_low_pctile = percentile_scores(
            rows, "kg_co2_reduced_per_kwh", high_value_good=False
        )
        for row in rows:
            fsa = row["fsa"]
            row["high_reduction_low_pressure_score"] = (
                reduction_pctile.get(fsa, 0.0) + electricity_low_pctile.get(fsa, 0.0)
            ) / 2
            row["high_pressure_low_efficiency_score"] = (
                electricity_high_pctile.get(fsa, 0.0) + efficiency_low_pctile.get(fsa, 0.0)
            ) / 2
        all_rows.extend(rows)
    return all_rows


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            output = {}
            for column in columns:
                value = row[column]
                if isinstance(value, float):
                    output[column] = "" if value is None or math.isnan(value) else f"{value:.6f}"
                elif value is None:
                    output[column] = ""
                else:
                    output[column] = value
            writer.writerow(output)


def scenario_summary(rows: list[dict]) -> list[dict]:
    summaries = []
    for year, scenario, label in SCENARIOS:
        subset = [row for row in rows if row["scenario"] == scenario]
        co2 = sum(row["scenario_co2_kt_per_year"] for row in subset)
        ref_co2 = sum(row["ref_co2_kt_per_year"] for row in subset)
        elec = sum(row["scenario_electricity_gwh_per_year"] for row in subset)
        ref_elec = sum(row["ref_electricity_gwh_per_year"] for row in subset)
        reduction = ref_co2 - co2
        elec_increase = elec - ref_elec
        summaries.append(
            {
                "year": year,
                "scenario": scenario,
                "scenario_label": label,
                "total_co2_reduction_kt_per_year": reduction,
                "total_electricity_increase_gwh_per_year": elec_increase,
                "fleet_tradeoff_kg_co2_per_kwh": reduction / elec_increase if elec_increase > 0 else None,
                "median_fsa_tradeoff_kg_co2_per_kwh": median(
                    row["kg_co2_reduced_per_kwh"]
                    for row in subset
                    if row["kg_co2_reduced_per_kwh"] is not None
                ),
            }
        )
    return summaries


def median(values) -> float | None:
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def draw_scatter(path: Path, rows: list[dict], title: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1200, 850
    ml, mr, mt, mb = 120, 70, 110, 115
    pw, ph = width - ml - mr, height - mt - mb
    xs = [max(0.0, row["electricity_increase_gwh_per_year"]) for row in rows]
    ys = [max(0.0, row["co2_reduction_kt_per_year"]) for row in rows]
    efficiencies = [row["kg_co2_reduced_per_kwh"] or 0.0 for row in rows]
    x_max = nice_max(max(xs) if xs else 1)
    y_max = nice_max(max(ys) if ys else 1)
    eff_min = min(efficiencies) if efficiencies else 0
    eff_max = max(efficiencies) if efficiencies else 1

    def x_for(value: float) -> float:
        return ml + value / x_max * pw

    def y_for(value: float) -> float:
        return mt + ph - value / y_max * ph

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=24)
    axis_font = ImageFont.load_default(size=17)
    label_font = ImageFont.load_default(size=15)
    small_font = ImageFont.load_default(size=13)
    draw.text((ml, 30), title, fill=(25, 25, 25), font=title_font)

    for i in range(5):
        x_tick = x_max * i / 4
        y_tick = y_max * i / 4
        x = x_for(x_tick)
        y = y_for(y_tick)
        draw.line([(x, mt), (x, mt + ph)], fill=(232, 232, 232))
        draw.line([(ml, y), (ml + pw, y)], fill=(232, 232, 232))
        draw.text((x, mt + ph + 12), f"{x_tick:.1f}", anchor="mt", fill=(55, 55, 55), font=small_font)
        draw.text((ml - 12, y), f"{y_tick:.1f}", anchor="rm", fill=(55, 55, 55), font=small_font)
    draw.line([(ml, mt), (ml, mt + ph), (ml + pw, mt + ph)], fill=(60, 60, 60), width=2)
    draw.text((ml + pw / 2, height - 45), "EV electricity demand increase vs. 2020 REF (GWh/year)", anchor="mm", fill=(35, 35, 35), font=axis_font)
    draw.text((ml, mt - 24), "CO2 reduction vs. 2020 REF (kt/year)", anchor="lm", fill=(35, 35, 35), font=axis_font)

    median_x = median(xs) or 0
    median_y = median(ys) or 0
    draw.line([(x_for(median_x), mt), (x_for(median_x), mt + ph)], fill=(150, 150, 150), width=1)
    draw.line([(ml, y_for(median_y)), (ml + pw, y_for(median_y))], fill=(150, 150, 150), width=1)

    for row in rows:
        x = x_for(max(0.0, row["electricity_increase_gwh_per_year"]))
        y = y_for(max(0.0, row["co2_reduction_kt_per_year"]))
        score = (row["kg_co2_reduced_per_kwh"] or eff_min) - eff_min
        denom = eff_max - eff_min if eff_max > eff_min else 1
        color = interpolate((222, 235, 247), (0, 109, 44), score / denom)
        r = 5
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline=(35, 35, 35))

    label_rows = sorted(rows, key=lambda row: row["high_reduction_low_pressure_score"], reverse=True)[:5]
    label_rows += sorted(rows, key=lambda row: row["high_pressure_low_efficiency_score"], reverse=True)[:5]
    seen = set()
    for row in label_rows:
        if row["fsa"] in seen:
            continue
        seen.add(row["fsa"])
        x = x_for(max(0.0, row["electricity_increase_gwh_per_year"]))
        y = y_for(max(0.0, row["co2_reduction_kt_per_year"]))
        draw.text((x + 8, y - 8), row["fsa"], fill=(20, 20, 20), font=label_font)

    draw.text(
        (ml + pw - 4, mt + 8),
        "Higher reduction\nhigher electricity demand",
        anchor="ra",
        fill=(90, 90, 90),
        font=small_font,
    )
    draw.text(
        (ml + 8, mt + 8),
        "Higher reduction\nlower electricity demand",
        anchor="la",
        fill=(30, 110, 55),
        font=small_font,
    )
    image.save(path)


def interpolate(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = min(1.0, max(0.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    residual = value / magnitude
    if residual <= 1:
        return magnitude
    if residual <= 2:
        return 2 * magnitude
    if residual <= 5:
        return 5 * magnitude
    return 10 * magnitude


def write_latex_summary(path: Path, summaries: list[dict], top_good: list[dict], top_pressure: list[dict]) -> None:
    lines = [
        "% Generated by data_post-processing/analyze_fsa_co2_electricity_tradeoff.py",
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{FSA-level CO$_2$ reduction and EV electricity demand trade-off by 2035 scenario.}",
        "\\label{tab:fsa-co2-electricity-tradeoff}",
        "\\scriptsize",
        "\\begin{tabular}{lrrr}",
        "\\toprule",
        "Scenario & CO$_2$ reduction & Electricity increase & Trade-off \\\\",
        " & (kt/year) & (GWh/year) & (kg CO$_2$/kWh) \\\\",
        "\\midrule",
    ]
    for row in summaries:
        lines.append(
            f"{row['scenario_label']} & "
            f"{format_number(row['total_co2_reduction_kt_per_year'])} & "
            f"{format_number(row['total_electricity_increase_gwh_per_year'])} & "
            f"{format_number(row['fleet_tradeoff_kg_co2_per_kwh'])} \\\\"
        )
    lines += [
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{Top FSA trade-off rankings across 2035 scenarios.}",
        "\\label{tab:fsa-tradeoff-rankings}",
        "\\scriptsize",
        "\\begin{tabular}{lllrrr}",
        "\\toprule",
        "Ranking & Scenario & FSA & CO$_2$ reduction & Electricity increase & Trade-off \\\\",
        " & & & (kt/year) & (GWh/year) & (kg CO$_2$/kWh) \\\\",
        "\\midrule",
    ]
    for row in top_good[:10]:
        lines.append(
            f"High reduction, low pressure & {row['scenario_label']} & {row['fsa']} & "
            f"{format_number(row['co2_reduction_kt_per_year'])} & "
            f"{format_number(row['electricity_increase_gwh_per_year'])} & "
            f"{format_number(row['kg_co2_reduced_per_kwh'])} \\\\"
        )
    lines.append("\\midrule")
    for row in top_pressure[:10]:
        lines.append(
            f"High pressure, low efficiency & {row['scenario_label']} & {row['fsa']} & "
            f"{format_number(row['co2_reduction_kt_per_year'])} & "
            f"{format_number(row['electricity_increase_gwh_per_year'])} & "
            f"{format_number(row['kg_co2_reduced_per_kwh'])} \\\\"
        )
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = build_tradeoff_rows()
    columns = [
        "year",
        "scenario",
        "scenario_label",
        "fsa",
        "population",
        "ref_co2_kt_per_year",
        "scenario_co2_kt_per_year",
        "co2_reduction_kt_per_year",
        "co2_reduction_percent",
        "co2_reduction_kg_per_person_year",
        "ref_electricity_gwh_per_year",
        "scenario_electricity_gwh_per_year",
        "electricity_increase_gwh_per_year",
        "electricity_increase_kwh_per_person_year",
        "kg_co2_reduced_per_kwh",
        "high_reduction_low_pressure_score",
        "high_pressure_low_efficiency_score",
    ]
    all_path = RESULTS_DIR / "fsa_co2_electricity_tradeoff_all_scenarios.csv"
    write_csv(all_path, rows, columns)

    summaries = scenario_summary(rows)
    summary_path = RESULTS_DIR / "fsa_co2_electricity_tradeoff_scenario_summary.csv"
    write_csv(
        summary_path,
        summaries,
        [
            "year",
            "scenario",
            "scenario_label",
            "total_co2_reduction_kt_per_year",
            "total_electricity_increase_gwh_per_year",
            "fleet_tradeoff_kg_co2_per_kwh",
            "median_fsa_tradeoff_kg_co2_per_kwh",
        ],
    )

    top_good = sorted(rows, key=lambda row: row["high_reduction_low_pressure_score"], reverse=True)
    top_pressure = sorted(rows, key=lambda row: row["high_pressure_low_efficiency_score"], reverse=True)
    top_good_path = RESULTS_DIR / "fsa_high_reduction_low_electricity_pressure_top10.csv"
    top_pressure_path = RESULTS_DIR / "fsa_high_electricity_pressure_low_efficiency_top10.csv"
    write_csv(top_good_path, top_good[:10], columns)
    write_csv(top_pressure_path, top_pressure[:10], columns)

    for _, scenario, label in SCENARIOS:
        subset = [row for row in rows if row["scenario"] == scenario]
        draw_scatter(
            RESULTS_DIR / f"fsa_co2_electricity_tradeoff_scatter_2035_{scenario}.png",
            subset,
            label,
        )

    write_latex_summary(
        RESULTS_DIR / "fsa_co2_electricity_tradeoff_tables.tex",
        summaries,
        top_good,
        top_pressure,
    )

    for path in [
        all_path,
        summary_path,
        top_good_path,
        top_pressure_path,
        RESULTS_DIR / "fsa_co2_electricity_tradeoff_tables.tex",
    ]:
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
