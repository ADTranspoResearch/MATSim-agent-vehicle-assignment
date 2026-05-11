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
