"""
Contains functions related to prediction the growth of the vehicle
fleet size.
"""

import csv
import pandas as pd
from matsim_vehicle_type.config import DATA_DIR


def calculate_vehicle_per_person(pop: int, fleet_size: int) -> float:
    veh_per_pers = fleet_size / pop
    return veh_per_pers


def get_historic_fleet_size() -> pd.DataFrame:
    """
    Reads each yearly personal vehicle SAAQ data fuke and returns a df
    containing every row for each year.

    Returns
    -------
    pd.DataFrame
        Dataframe containing the year, size, and new/exit vehicle
        designation of every row in all SAAQ databases.
    """

    fleet_path = DATA_DIR / "vehicles" / "ownership" / "personal_ownership"
    fleet_size_path = fleet_path / "historic_fleet_size.csv"

    dtype_map = {
        "MOD": "string",
        "CYL2": "string",
        "CARB": "string",
        "Motorisation": "string",
        "Genre": "string",
        "Hybrid Type": "string",
        "Propulsion": "string",
    }
    if fleet_size_path.exists():

        df = pd.read_csv(
            fleet_size_path, dtype={"year": int, "size": int, "new": int, "exit": int}
        )
    else:
        rows = []
        for i in range(2013, 2021):
            filename = f"Personal_McGill_SAAQ_{i}_2024-01-10.csv"
            filepath = fleet_path / filename
            print(f"running {filename}.")

            df_year = pd.read_csv(filepath, dtype=dtype_map)
            rows.append(
                {
                    "year": i,
                    "size": df_year.shape[0],
                    "new": df_year.loc[df_year["Entrant"] == 1].shape[0],
                    "exit": df_year.loc[df_year["Sortant"] == 1].shape[0],
                }
            )
        df = pd.DataFrame(rows)
        df.to_csv(fleet_size_path, index=False)

    return df


def read_historic_population(filename: str) -> pd.DataFrame:
    """
    Reads the quebec historical population file and extracts the yearly
    population based on the 1st quarter.
    Returns a dataframe with each years population.

    Parameters
    ----------
    filename : str
        Relative path to the population file.

    Returns
    -------
    pd.DataFrame
        Yearly population of Quebec extracted from file.
    """
    pop_file = DATA_DIR / "population" / filename
    df = pd.read_csv(pop_file, index_col="year", thousands=",")
    df = df.loc[df["quarter"] == 1]
    return df


def predict_fleet_over_time(
    historic_fleet: pd.DataFrame,
    historic_population: pd.DataFrame,
    predicted_composition: pd.DataFrame,
) -> pd.DataFrame:
    """
    Takes historic fleet, predicted growth, new vehicle composition, and
    simulates the changes to the fleet for the total number of years
    that have a projected population.

    Returns a dataframe that contains the total number of vehicles of
    each vehicle type for every year that is predicted

    Parameters
    ----------
    historic_fleet : pd.DataFrame
        Latest historical data containing the total number of vehicles
        of each type in the fleet.
    historic_population : pd.DataFrame
        Provides the growth patters of the fleet. Columns should contain
        fleet growth, number of new vehicles entering fleet, and number
        of vehicles exiting fleet. Must have rows for the lastest year
        in the composition dataframe.
    predicted_composition : pd.DataFrame
        Provides the predicted vehicle type composition of the new
        vehicles entering the fleet for each year. Rows are the vehicle
        types and columns are the predicted years. Function will
        simulate fleet dynamics up until the last year provided by
        this dataframe.

    Returns
    -------
    pd.DataFrame
        Provides the number of vehicles of each vehicle type (row) for
        every simulated year (column), also saves it to a file.
    """
    # Predict fleet change over time

    base_counts = historic_fleet.set_index("vehicle_type")["count"]

    # Create output dataframe
    result_df = pd.DataFrame(index=base_counts.index)

    # Store initial year (2020)
    result_df[2020] = base_counts

    # Ensure prediction years are sorted numerically
    prediction_years = sorted(predicted_composition.columns)

    exiting_proportions = result_df[2020] / result_df[2020].sum()
    for year in prediction_years:

        previous_year = year - 1

        # Total fleet growth for this year
        growth = historic_population.loc[year, "new"]

        # Previous year's fleet totals
        previous_totals = result_df[previous_year]

        # Composition ratios for NEW vehicles entering the fleet
        composition_ratios = predicted_composition[year]

        # Number of new vehicles added for each type
        additions = growth * composition_ratios

        # Number of removed vehicles from each type
        total_exit = historic_population.loc[year, "implied_exit"]
        if total_exit >= 0:
            exiting = exiting_proportions * total_exit
        else:
            exiting = exiting_proportions * 0

        # New fleet totals
        result_df[year] = previous_totals + additions - exiting

    result_df.to_csv("predicted_fleet_composition.csv")
    print(result_df)
    return result_df
