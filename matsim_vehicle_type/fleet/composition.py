"""
Contains functions related to prediction the vehicle type composition
of the new vehicles entering the fleet each year.
"""

from math import e, log10
import pandas as pd
from matsim_vehicle_type.vehicles.vehicle_assignment import get_vehicle_type


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

    df["vehicle_type"] = df.apply(get_vehicle_type, axis=1)
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
        vehicle_type_df = full_df.loc[full_df["vehicle_type"] == vehicle_type]
        vehicle_type_df["abs_growth"] = (
            vehicle_type_df["count"] - vehicle_type_df["count"].shift()
        )
        vehicle_type_df["rel_growth"] = (
            vehicle_type_df["abs_growth"] / vehicle_type_df["count"]
        )
        growth_trends[vehicle_type] = vehicle_type_df["rel_growth"].to_list()
        avg_growth_trends[vehicle_type] = vehicle_type_df["rel_growth"].mean()
    print(growth_trends)
    return avg_growth_trends


def log_growth(initial: float, alpha: float, time: int) -> float:
    """
    Returns the growth of a population based on a log growth rate.

    Should be deprecated.
    """
    return initial + time * log10(1 + alpha)


def predict_composition_trend(
    initial_composition: dict[float],
    average_growth: dict[float],
    start_year=2021,
    end_year=2030,
) -> pd.DataFrame:
    """
    Takes an initial fleet composition and predicts the changes to the
    composition year by year for the specified number of years.
    Returns a Dataframe with the yearly compositions
    """
    df_rows = {}
    new_share = initial_composition
    for i in range(start_year, end_year):
        row = {}
        growth_weight = {}
        for vehicle_type, market_share in initial_composition.items():
            growth_weight[vehicle_type] = average_growth[vehicle_type] + 1
        new_share = multiply_reweight(new_share, growth_weight)
        df_rows[i] = new_share
    df = pd.DataFrame.from_dict(df_rows)
    print(df)
    return df
