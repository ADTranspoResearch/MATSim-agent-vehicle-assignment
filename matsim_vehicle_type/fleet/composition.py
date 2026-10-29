"""
Contains functions related to prediction the vehicle type composition
of the new vehicles entering the fleet each year.
"""

from math import e, log10, exp, log, isfinite
from warnings import warn
import pandas as pd
# from matsim_vehicle_type.vehicles.vehicle_assignment import get_vehicle_type
from matsim_vehicle_type.config import SCN_CASE, SCN_CONFIGS


def softmax(scores: dict[str, float]) -> dict[str, float]:
    """
    Takes a dict containing scores of keys and applies softmax to values
    to normalize the scores between 0-1 relative to eachother.

    Parameters
    ----------
    scores : dict string keys float values
        Utility cores of each key in dict. Scores can be any value.

    Returns
    -------
    dict[str, float]
        normalized scores relative to eachother. Values range from 0-1
        and all values sum up to 1.

    Should be deprecated.
    """
    if len(scores) < 1:
        raise ValueError("Softmax scores cannot be empty.")
    sf_dict = {}
    exp_sum = 0
    for score in list(scores.values()):
        exp_sum += e**score
    for key, value in scores.items():
        sf_dict[key] = (e**value) / exp_sum
    return sf_dict


def multiply_reweight(
    previous_proportions: dict[str, float], growth_weight: dict[str, float]
) -> dict[str:float]:
    """
    Takes a weighted average of the values in the "previous_proportions"
    multiplied by their corresponding "growth_weight" values.

    Parameters
    ----------
    previous_proportions : dict[str:float]
        Previously used proportion of each vehicle type in the
        composition.

    growth_weight : dict[str:float]
        Value determines how much each proportion will grow in the next
        iteration. Higher growth rates lead to larger proportion taken
        up by that vehicle type.
    Returns
    -------
    dict[str:float]
        New proportions to be used by the new vehicle composition.
    """

    weight_dict = {}
    mult_sum = 0
    for vehicle_type, weight in growth_weight.items():
        mult_sum += weight * previous_proportions[vehicle_type]
    for vehicle_type, weight in growth_weight.items():
        weight_dict[vehicle_type] = (
            weight * previous_proportions[vehicle_type] / mult_sum
        )
    return weight_dict


def historic_fleet_composition(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the historic SAAQ data and returns the counts of the different
    vehicle types.

    Parameters
    ----------
    df : pd.DataFrame
        Full historic SAAQ database.

    Returns
    -------
    pd.DataFrame
        Total counts of each vehicle type in the database for each year.
    """

    df = df[~df["vehicle_type"].isin(["unknown", "other", "hev_van/pickup"])]
    historic_veh_type = (
        df.groupby(["AnneeSAAQ", "vehicle_type"])
        .size()
        .reset_index(name="count")
        .sort_values(["vehicle_type", "AnneeSAAQ"])
    )
    return historic_veh_type


def get_growth_trends(composition: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Takes a list of dfs that contain the total number of vehicles
    belonging to each vehicle type and returns the yearly growth rate
    for each vehicle type.

    Parameters
    ----------
    composition : list[pd.DataFrame]
        All historic vehicle count data available.

    Returns
    -------
    pd.DataFrame
        Rows are vehicle types and each year is a column with the growth
        rate for that corresponding vehicle type.
    """

    full_df = pd.concat(composition, ignore_index=True)
    vehicle_types = full_df["vehicle_type"].unique()

    growth_trends = {}
    avg_growth_trends = {}
    for vehicle_type in vehicle_types:
        vehicle_type_df = full_df.loc[
            full_df["vehicle_type"] == vehicle_type
        ].copy()
        vehicle_type_df.loc[:, "abs_growth"] = (
            vehicle_type_df["count"] - vehicle_type_df["count"].shift()
        )
        vehicle_type_df.loc[:, "rel_growth"] = (
            vehicle_type_df["abs_growth"] / vehicle_type_df["count"].shift()
        )
        growth_trends[vehicle_type] = vehicle_type_df["rel_growth"].to_list()
        avg_growth_trends[vehicle_type] = vehicle_type_df["rel_growth"].mean()
        # print(growth_trends)
    return avg_growth_trends


def log_growth(initial: float, alpha: float, time: int) -> float:
    """
    Returns the growth of a population based on a log growth rate.

    Should be deprecated.
    """
    return initial + time * log10(1 + alpha)

# def _clip_share(value: float, eps: float = 1e-9) -> float:
#     return min(max(float(value), eps), 1.0 - eps)


# def _logit_with_ceiling(y: float, k: float) -> float:
#     y = _clip_share(y)
#     k = max(float(k), y + 1e-9)
#     return log(y / (k - y))


# def _fit_ev_logit_fixed_ceiling(
#     anchor_points: dict[int, float],
#     ceiling: float = 1.0,
#     fit_years: tuple[int, int] = (2020, 2035),
# ) -> tuple[float, float, float]:
#     """
#     Fits electric share with fixed K:

#         y(t) = K / (1 + exp(-r * (t - t0)))

#     K is fixed by `ceiling`.
#     r and t0 are solved from two anchor points.
#     """
#     year_a, year_b = fit_years

#     if year_a not in anchor_points or year_b not in anchor_points:
#         raise ValueError(f"Missing EV anchor years: {fit_years}")

#     k = float(ceiling)

#     y_a = _clip_share(anchor_points[year_a])
#     y_b = _clip_share(anchor_points[year_b])

#     if y_a >= k or y_b >= k:
#         raise ValueError(
#             f"EV anchor share must be below ceiling K={k}. "
#             f"Got {year_a}={y_a}, {year_b}={y_b}."
#         )

#     z_a = log(y_a / (k - y_a))
#     z_b = log(y_b / (k - y_b))

#     r = (z_b - z_a) / (year_b - year_a)

#     if abs(r) < 1e-12:
#         raise ValueError("Cannot fit EV logit because anchor shares are equal.")

#     t0 = year_a - z_a / r

#     return k, r, t0


# def refit_ev_with_logit(
#     initial_composition: dict[str, float],
#     baseline_df: pd.DataFrame,
#     anchor_years: tuple[int, int, int] = (2020, 2024, 2035),
#     ev_type: str = "electric",
#     max_ceiling: float = 1.0,
# ) -> pd.DataFrame:
#     """
#     Refit only EV new-vehicle share with a logistic curve.

#     2020 comes from initial_composition.
#     2024 and 2035 come from the existing predicted baseline_df.

#     Other vehicle types keep their baseline relative proportions and are
#     rescaled to fill 1 - EV share.
#     """
#     if ev_type not in initial_composition:
#         raise ValueError(f"{ev_type!r} is missing from initial_composition.")

#     if ev_type not in baseline_df.index:
#         raise ValueError(f"{ev_type!r} is missing from baseline_df.")

#     first_anchor_year = min(anchor_years)

#     missing_anchor_years = [
#         year
#         for year in anchor_years
#         if year != first_anchor_year and year not in baseline_df.columns
#     ]
#     if missing_anchor_years:
#         raise ValueError(
#             "Missing anchor years in predicted composition: "
#             f"{missing_anchor_years}"
#         )

#     anchor_points = {}

#     for year in anchor_years:
#         if year == first_anchor_year:
#             anchor_points[year] = initial_composition[ev_type]
#         else:
#             anchor_points[year] = baseline_df.loc[ev_type, year]

#     k, r, t0 = _fit_ev_logit_fixed_ceiling(
#     anchor_points,
#     ceiling=max_ceiling,
#     fit_years=(2020, 2035),
#     )

#     df = baseline_df.copy()

#     for year in df.columns:
#         ev_target = k / (1 + exp(-r * (year - t0)))
#         ev_target = _clip_share(ev_target)

#         ev_old = _clip_share(df.loc[ev_type, year])
#         non_ev_old_total = 1 - ev_old
#         non_ev_new_total = 1 - ev_target

#         if non_ev_old_total <= 0:
#             raise ValueError(f"Non-EV share is zero in year {year}.")

#         scale = non_ev_new_total / non_ev_old_total

#         for vehicle_type in df.index:
#             if vehicle_type == ev_type:
#                 df.loc[vehicle_type, year] = ev_target
#             else:
#                 df.loc[vehicle_type, year] = df.loc[vehicle_type, year] * scale

#     return df

def _clip_share(value: float, eps: float = 1e-9) -> float:
    return min(max(float(value), eps), 1.0 - eps)

def find_ev_plateau_or_peak_year(
    baseline_df: pd.DataFrame,
    ev_type: str = "electric",
    min_year: int = 2030,
    min_delta: float = 0.005,
) -> int:
    ev_share = baseline_df.loc[ev_type].sort_index()
    deltas = ev_share.diff()

    for year in ev_share.index:
        if year < min_year:
            continue

        delta = deltas.loc[year]

        if 0 <= delta <= min_delta:
            return int(year)

    return int(ev_share.idxmax())

def _fit_ev_gompertz_fixed_bounds(
    anchor_points: dict[int, float],
    lower: float = 0.0,
    upper: float = 1.0,
    fit_years: tuple[int, int] = (2020, 2035),
    base_year: int = 2020,
) -> tuple[float, float, float, int]:
    """
    Fits EV share with a Gompertz curve:

        y(t) = L + (U - L) * exp[-a * exp(-k * t)]

    L and U are fixed.
    a and k are solved from two anchor years.
    """
    year_a, year_b = fit_years

    if year_a not in anchor_points or year_b not in anchor_points:
        raise ValueError(f"Missing EV anchor years: {fit_years}")

    lower = float(lower)
    upper = float(upper)

    if not lower < upper:
        raise ValueError("Gompertz lower bound must be below upper bound.")

    y_a = _clip_share(anchor_points[year_a])
    y_b = _clip_share(anchor_points[year_b])

    if not lower < y_a < upper or not lower < y_b < upper:
        raise ValueError(
            "EV anchor shares must be between lower and upper bounds. "
            f"Got {year_a}={y_a}, {year_b}={y_b}, "
            f"lower={lower}, upper={upper}."
        )

    t_a = year_a - base_year
    t_b = year_b - base_year

    if t_a == t_b:
        raise ValueError("Gompertz fit years must be distinct.")

    normalized_a = (y_a - lower) / (upper - lower)
    normalized_b = (y_b - lower) / (upper - lower)

    z_a = -log(normalized_a)
    z_b = -log(normalized_b)

    if z_a <= 0 or z_b <= 0:
        raise ValueError("Invalid Gompertz transform for anchor shares.")

    k = -log(z_b / z_a) / (t_b - t_a)
    a = z_a / exp(-k * t_a)

    return lower, upper, a, k, base_year


def refit_ev_with_gompertz(
    initial_composition: dict[str, float],
    baseline_df: pd.DataFrame,
    ev_type: str = "electric",
    lower: float = 0.0,
    upper: float = 1.0,
    min_plateau_year: int = 2030,
    min_delta: float = 0.005,
) -> pd.DataFrame:
    """
    Legacy two-anchor EV Gompertz refit, retained for explicit comparisons.

    The first anchor comes from initial_composition; the second is the
    selected first-stage plateau/peak year. The production prediction entry
    point now uses refit_ev_with_all_predictions instead.

    Other vehicle types keep their baseline relative proportions and are
    rescaled to fill 1 - EV share.
    """
    if ev_type not in initial_composition:
        raise ValueError(f"{ev_type!r} is missing from initial_composition.")

    if ev_type not in baseline_df.index:
        raise ValueError(f"{ev_type!r} is missing from baseline_df.")

    first_anchor_year = min(baseline_df.columns) - 1


    plateau_or_peak_year = find_ev_plateau_or_peak_year(
        baseline_df,
        ev_type=ev_type,
        min_year=min_plateau_year,
        min_delta=min_delta,
    )

    anchor_points = {
        first_anchor_year: initial_composition[ev_type],
        plateau_or_peak_year: baseline_df.loc[ev_type, plateau_or_peak_year],
    }

    lower, upper, a, k, base_year = _fit_ev_gompertz_fixed_bounds(
        anchor_points,
        lower=lower,
        upper=upper,
        fit_years=(first_anchor_year, plateau_or_peak_year),
        base_year=first_anchor_year,
    )

    df = baseline_df.copy()

    for year in df.columns:
        t = year - base_year
        ev_target = lower + (upper - lower) * exp(-a * exp(-k * t))
        ev_target = _clip_share(ev_target)

        ev_old = _clip_share(df.loc[ev_type, year])
        non_ev_old_total = 1 - ev_old
        non_ev_new_total = 1 - ev_target

        if non_ev_old_total <= 0:
            raise ValueError(f"Non-EV share is zero in year {year}.")

        scale = non_ev_new_total / non_ev_old_total

        for vehicle_type in df.index:
            if vehicle_type == ev_type:
                df.loc[vehicle_type, year] = ev_target
            else:
                df.loc[vehicle_type, year] = df.loc[vehicle_type, year] * scale

    return df

def apply_ev_gompertz_scenario_from_scaled_target(
    df: pd.DataFrame,
    ev_type: str = "electric",
    anchor_year: int = 2024,
    target_year: int = 2035,
    target_factor: float = 1.25,
    lower: float = 0.0,
    ceiling: float = 1.0,
    min_target_delta: float = 1e-9,
) -> pd.DataFrame:
    """
    Keep years <= anchor_year unchanged.

    For later years, refit EV share with a Gompertz curve:

        y(t) = L + (U - L) * exp[-a * exp(-k * t)]

    using:
        anchor_year EV share from baseline
        target_year EV share * target_factor from baseline

    Other vehicle types keep their baseline relative proportions and are
    rescaled to sum with EV share to 1.
    """
    if ev_type not in df.index:
        raise ValueError(f"{ev_type!r} is missing from composition df.")

    if anchor_year not in df.columns:
        raise ValueError(f"Anchor year {anchor_year} is missing from df.")

    if target_year not in df.columns:
        raise ValueError(f"Target year {target_year} is missing from df.")

    scenario_df = df.copy()

    y_anchor = _clip_share(df.loc[ev_type, anchor_year])
    y_target_old = _clip_share(df.loc[ev_type, target_year])
    y_target = y_target_old * target_factor
    y_target = min(y_target, ceiling - 1e-9)

    if y_target <= y_anchor:
        adjusted_target = min(y_anchor + min_target_delta, ceiling - 1e-9)
        warn(
            "Scenario target is not above anchor EV share; using the "
            "minimum monotonic target instead. "
            f"Got anchor {anchor_year}={y_anchor}, "
            f"scaled target {target_year}={y_target}, "
            f"adjusted target={adjusted_target}.",
            RuntimeWarning,
            stacklevel=2,
        )
        y_target = adjusted_target

    anchor_points = {
        anchor_year: y_anchor,
        target_year: y_target,
    }
    lower, upper, a, k, base_year = _fit_ev_gompertz_fixed_bounds(
        anchor_points,
        lower=lower,
        upper=ceiling,
        fit_years=(anchor_year, target_year),
        base_year=anchor_year,
    )

    for year in scenario_df.columns:
        if year <= anchor_year:
            continue

        t = year - base_year
        ev_target = lower + (upper - lower) * exp(-a * exp(-k * t))
        ev_target = _clip_share(ev_target)

        ev_old = _clip_share(df.loc[ev_type, year])
        non_ev_old_total = 1 - ev_old
        non_ev_new_total = 1 - ev_target

        if non_ev_old_total <= 0:
            raise ValueError(f"Non-EV share is zero in year {year}.")

        scale = non_ev_new_total / non_ev_old_total

        for vehicle_type in scenario_df.index:
            if vehicle_type == ev_type:
                scenario_df.loc[vehicle_type, year] = ev_target
            else:
                scenario_df.loc[vehicle_type, year] = df.loc[vehicle_type, year] * scale

    return scenario_df


def apply_ev_logit_scenario_from_scaled_target(*args, **kwargs) -> pd.DataFrame:
    """
    Backward-compatible alias for the Gompertz scaled-target scenario.

    The old implementation used a logistic curve. Scenario configs that still
    refer to "ev_logit_scaled_target" now use the Gompertz model.
    """
    return apply_ev_gompertz_scenario_from_scaled_target(*args, **kwargs)

def project_composition_first_stage(
    initial_composition: dict[str, float],
    average_growth: dict[str, float],
    start_year=2021,
    end_year=2030,
) -> pd.DataFrame:
    """Run the original recurrence without any curve or scenario adjustment.

    ``end_year`` is exclusive, as in ``predict_composition_trend``.
    """
    if not isinstance(start_year, int) or not isinstance(end_year, int) or end_year <= start_year:
        raise ValueError("The first-stage interval must contain integer forecast years.")
    if not initial_composition or any(not isfinite(value) or value < 0 for value in initial_composition.values()):
        raise ValueError("Initial shares must be finite and nonnegative.")
    if abs(sum(initial_composition.values()) - 1) > 1e-9:
        raise ValueError("Initial composition must sum to one.")
    if any(key not in average_growth or not isfinite(average_growth[key]) for key in initial_composition):
        raise ValueError("Each initial vehicle type requires a finite historical growth rate.")
    df_rows = {}
    new_share = initial_composition
    for i in range(start_year, end_year):
        growth_weight = {}
        for vehicle_type in initial_composition:
            if vehicle_type == "electric":
                current_ev_share = new_share[vehicle_type]
                max_growth = average_growth[vehicle_type]
                growth_weight[vehicle_type] = 1 + max_growth * (1 - current_ev_share)
            else:
                growth_weight[vehicle_type] = average_growth[vehicle_type] + 1
        new_share = multiply_reweight(new_share, growth_weight)
        df_rows[i] = new_share
    return pd.DataFrame.from_dict(df_rows)


def refit_ev_with_all_predictions(initial_composition, first_stage_df, fit_end_year=2040):
    """Fit all first-stage EV targets up to a fixed, inclusive calibration end."""
    from matsim_vehicle_type.fleet.gompertz_projection import fit_projected_ev_gompertz, replace_ev_shares

    fit_years = [int(year) for year in first_stage_df.columns if year <= fit_end_year]
    anchor_year = int(min(first_stage_df.columns)) - 1
    fit = fit_projected_ev_gompertz(
        fit_years, first_stage_df.loc["electric", fit_years], anchor_year, initial_composition["electric"]
    )
    result = replace_ev_shares(first_stage_df, fit.predict(first_stage_df.columns))
    result.attrs["gompertz"] = {
        "model": "all_prediction_gompertz", "fit_end_year": fit_end_year,
        "baseline_fit": fit.to_dict(),
        "baseline_targets": [{"year": year, "target_share": float(first_stage_df.loc["electric", year])}
                             for year in fit_years],
        "scenario_fit": None, "scenario_targets": [], "clipped_target_count": 0,
    }
    return result


def apply_ev_gompertz_scenario_from_scaled_predictions(
    baseline_df, first_stage_df, *, anchor_year=2024, factor=1.25, fit_end_year=2040, ceiling=1.0,
):
    """Fit scaled raw EV targets after a shared BAU anchor, with fixed K=1.

    The factor scales the first-stage shares, not annual growth rates or the
    fitted BAU. Targets are clipped to [0, 1]; clipping is exposed in attrs.
    """
    from copy import deepcopy
    from matsim_vehicle_type.fleet.gompertz_projection import fit_projected_ev_gompertz, replace_ev_shares

    if not isfinite(factor) or factor <= 0:
        raise ValueError("The projection scaling factor must be positive and finite.")
    if ceiling != 1.0:
        raise ValueError("All-prediction scenarios currently require ceiling=1.")
    if factor == 1:
        result = baseline_df.copy()
        result.attrs = deepcopy(baseline_df.attrs)
        result.attrs.setdefault("gompertz", {})["scenario_factor"] = 1.0
        return result
    if anchor_year not in baseline_df.columns or not isinstance(anchor_year, int):
        raise ValueError(f"Missing integer BAU scenario anchor year: {anchor_year}")
    if not first_stage_df.columns.equals(baseline_df.columns) or not first_stage_df.index.equals(baseline_df.index):
        raise ValueError("BAU and first-stage matrices must have matching years and vehicle types.")
    fit_years = [int(year) for year in first_stage_df.columns if anchor_year < year <= fit_end_year]
    target_records = []
    for year in fit_years:
        original = float(first_stage_df.loc["electric", year])
        if not isfinite(original) or not 0 <= original <= 1:
            raise ValueError(f"Invalid first-stage EV target for {year}: {original}")
        scaled = factor * original
        target = min(1.0, max(0.0, scaled))
        target_records.append({"year": year, "first_stage_share": original,
                               "scaled_target_share": scaled, "target_share": target,
                               "clipped": target != scaled})
    fit = fit_projected_ev_gompertz(
        fit_years, [row["target_share"] for row in target_records],
        anchor_year, float(baseline_df.loc["electric", anchor_year]),
    )
    ev_shares = baseline_df.loc["electric"].copy()
    future = baseline_df.columns[baseline_df.columns > anchor_year]
    ev_shares.loc[future] = fit.predict(future)
    result = replace_ev_shares(first_stage_df, ev_shares)
    # Preserve the shared prefix exactly, including non-EV shares.
    result.loc[:, result.columns <= anchor_year] = baseline_df.loc[:, baseline_df.columns <= anchor_year]
    result.attrs = deepcopy(baseline_df.attrs)
    result.attrs.setdefault("gompertz", {}).update({
        "scenario_factor": float(factor), "scenario_fit": fit.to_dict(),
        "scenario_targets": target_records,
        "clipped_target_count": sum(row["clipped"] for row in target_records),
    })
    return result


def predict_composition_trend(
    initial_composition: dict[str, float],
    average_growth: dict[str, float],
    start_year=2021,
    end_year=2030,
    scenario=None,
    *,
    gompertz_fit_end_year=2040,
) -> pd.DataFrame:
    """Project entering-vehicle shares using an all-prediction Gompertz fit.

    The first stage and calibration always cover the inclusive
    ``gompertz_fit_end_year``. ``end_year`` only controls the exclusive export
    end, so overlapping predictions are invariant to output horizon changes.
    Explicit scenarios do not mutate global configuration. Fit diagnostics
    and clipped scenario targets are available in ``result.attrs['gompertz']``.
    ``refit_ev_with_gompertz`` remains the legacy two-anchor comparator.
    """
    if not isinstance(gompertz_fit_end_year, int) or gompertz_fit_end_year <= start_year:
        raise ValueError("At least two first-stage calibration years are required.")
    if not isinstance(end_year, int) or end_year <= start_year:
        raise ValueError("The output interval must contain integer forecast years.")
    if "electric" not in initial_composition:
        raise ValueError("All-prediction Gompertz requires an observed EV initial share.")
    raw = project_composition_first_stage(
        initial_composition, average_growth, start_year, max(end_year, gompertz_fit_end_year + 1)
    )
    df = refit_ev_with_all_predictions(initial_composition, raw, gompertz_fit_end_year)

    scenario = SCN_CASE if scenario is None else scenario
    df.attrs["gompertz"]["scenario"] = scenario
    if scenario in SCN_CONFIGS:
        cfg = SCN_CONFIGS[scenario]
        if cfg["type"] == "ev_gompertz_scaled_projection":
            df = apply_ev_gompertz_scenario_from_scaled_predictions(
                df, raw, anchor_year=cfg.get("anchor_year", 2024), factor=cfg.get("factor", 1.25),
                fit_end_year=gompertz_fit_end_year, ceiling=cfg.get("ceiling", 1.0),
            )
        elif cfg["type"] in {"ev_gompertz_scaled_target", "ev_logit_scaled_target"}:
            # Compatibility for saved configurations and the GUI helper.
            df = apply_ev_gompertz_scenario_from_scaled_target(
                df, ev_type="electric", anchor_year=cfg.get("anchor_year", 2024),
                target_year=cfg.get("target_year", 2035), target_factor=cfg.get("factor", 1.25),
                lower=cfg.get("lower", 0.0), ceiling=cfg.get("ceiling", 1.0),
                min_target_delta=cfg.get("min_target_delta", 1e-9),
            )
        elif cfg["type"] != "none":
            for year in df.columns:
                electric_old = df.loc["electric", year]
                if cfg["type"] == "scale":
                    electric_target = electric_old * cfg["factor"]
                elif cfg["type"] == "target":
                    if year in cfg["targets"]:
                        electric_target = cfg["targets"][year]
                    elif year > max(cfg["targets"].keys()):
                        electric_target = cfg["targets"][max(cfg["targets"].keys())]
                    else:
                        continue  
                        

                if electric_old < 1:
                    scale = (1 - electric_target) / (1 - electric_old)
                    for vehicle_type in df.index:
                        if vehicle_type != "electric":
                            df.loc[vehicle_type, year] = df.loc[vehicle_type, year] * scale
                            
                df.loc["electric", year] = electric_target


    return df.loc[:, list(range(start_year, end_year))].copy()
