#!/usr/bin/env python3
"""Run the 100% MATSim daily FSA experiment matrix (25 runs by default)."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import _setup_path  # noqa: F401


def parser():
    # Keep --help/--dry-run independent of optional analysis dependencies.
    root = Path(__file__).resolve().parents[1]
    result = argparse.ArgumentParser(description=__doc__)
    paths = {
        "events": "data/MATSim/events/output_events_100.xml.gz",
        "vehicles": "data/MATSim/vehicles/output_allVehicles_with_events_100_ids.xml.gz",
        "network": "data/MATSim/network/network_0409.xml",
        "fsa-lookup": "data/FSA/agent_id_fsa_table.csv",
        "fsa-shapes": "data/FSA/quebec_fsa/quebec_fsa.shp",
        "ownership-dir": "data/vehicles/ownership/personal_ownership",
        "population-dir": "data/population/fsa_projected_pop",
        "reference-shares": "data/vehicles/fsa_vehicle_share_2020.parquet",
        "bev-shares": "data_post-processing/results/battery_electric_vehicle_type_share_quebec.csv",
        "emission-module": "matsim-emissions",
        "output-dir": "output/batch_100",
    }
    for name, default in paths.items():
        result.add_argument(f"--{name}", type=Path, default=root / default)
    result.add_argument("--scenarios", nargs="+", choices=["2020_REF", "2035_bau", "2035_acc_adopt", "2035_del_adopt", "2035_pol_align"],
                        default=["2020_REF", "2035_bau", "2035_acc_adopt", "2035_del_adopt", "2035_pol_align"])
    result.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    result.add_argument("--stage", choices=["all", "prepare", "assign", "summarize"], default="all",
                        help="prepare: cache inputs; assign: also write vehicles; summarize: use existing emission dumps")
    result.add_argument("--coordinates-crs", default="EPSG:32187")
    result.add_argument("--java-heap", default="4g")
    result.add_argument("--chunksize", type=int, default=300000)
    result.add_argument("--no-resume", action="store_true", help="Recompute selected stages even with valid completion records")
    result.add_argument("--keep-emission-events", action="store_true", help="Retain large generated dumps; requires sufficient disk space")
    result.add_argument("--dry-run", action="store_true", help="Print inputs and run matrix only; do not read data, write files, or invoke Java")
    return result


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if any(seed < 0 for seed in args.seeds) or len(set(args.seeds)) != len(args.seeds):
        argument_parser.error("Seeds must be distinct, nonnegative integers")
    if len(set(args.scenarios)) != len(args.scenarios):
        argument_parser.error("Scenarios must be distinct")
    if args.chunksize <= 0:
        argument_parser.error("--chunksize must be positive")
    if not re.fullmatch(r"[1-9][0-9]*[kKmMgG]", args.java_heap):
        argument_parser.error("--java-heap must be a size such as 4g or 4096m")
    if args.dry_run:
        print(f"Events: {args.events.resolve()}")
        print(f"Vehicles: {args.vehicles.resolve()}")
        print(f"Output: {args.output_dir.resolve()}")
        print(f"Stage: {args.stage}; expansion factor: 1; daily results only")
        for scenario in args.scenarios:
            for seed in args.seeds:
                print(f"  {scenario}/seed{seed}")
        print(f"{len(args.scenarios) * len(args.seeds)} runs; no files created")
        return 0
    from matsim_vehicle_type.batch import BatchOptions, run_batch

    values = vars(args).copy()
    values["resume"] = not values.pop("no_resume")
    values.pop("dry_run")
    values["scenarios"], values["seeds"] = tuple(values["scenarios"]), tuple(values["seeds"])
    for name in ("events", "vehicles", "network", "fsa_lookup", "fsa_shapes", "ownership_dir", "population_dir",
                 "reference_shares", "bev_shares", "emission_module", "output_dir"):
        values[name] = values[name].resolve()
    try:
        run_batch(BatchOptions(**values))
    except KeyboardInterrupt:
        print("Interrupted; generated files are retained. Repeat the command to resume.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Batch failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
