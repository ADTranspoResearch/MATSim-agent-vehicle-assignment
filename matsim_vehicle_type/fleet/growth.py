"""
Contains functions related to prediction the growth of the vehicle
fleet size.
"""

import csv
import pandas as pd
import numpy as np  
from matsim_vehicle_type.config import DATA_DIR, DTYPE_MAP, PC_QC, PC_QCP, SCN_CASE, SCN_CONFIGS


def calculate_vehicle_per_person(pop: int, fleet_size: int) -> float:
    veh_per_pers = fleet_size / pop
    return veh_per_pers


def get_historic_fleet_size(fsa_code:str) -> pd.DataFrame:
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
    fleet_size_path = fleet_path / f"{fsa_code}_historic_fleet_size.csv"
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
            df_year = pd.read_csv(filepath, dtype=DTYPE_MAP)

            if fsa_code == "H0H":
                df_year = df_year.loc[df_year['RTA'].isin(PC_QCP)].copy()
            elif fsa_code == "Q0Q":
                df_year = df_year.loc[df_year['RTA'].isin(PC_QC)].copy()
            else:  
                df_year = df_year.loc[df_year['RTA'] == fsa_code].copy()

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
        # print(df)

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
    return df


def predict_fleet_over_time(
    historic_fleet: pd.DataFrame,
    historic_population: pd.DataFrame,
    predicted_composition: pd.DataFrame,
    fsa_code: str
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
    combined_fleet = pd.concat(historic_fleet, ignore_index=True)
    df_result = combined_fleet.pivot(
        index="vehicle_type", columns="AnneeSAAQ", values="count"
    )
    df_result = df_result.fillna(0).astype(int)  
    print(df_result[2019])

    # Ensure prediction years are sorted numerically
    prediction_years = sorted(predicted_composition.columns)
    available_years = sorted(df_result.columns)


    for year in prediction_years:

        start_year = year - 10
        previous_year = year - 1

        years = list(range(start_year, previous_year + 1))
        used_years = [
            y if y in available_years else available_years[0]
            for y in years
        ]

        weights = np.arange(
            len(years),
            0,
            -1
        )

        weighted_fleet = df_result[used_years].mul(
            weights,
            axis=1
        )
        avg_fleet = weighted_fleet.sum(axis=1) / weights.sum()

        exit_proportions = avg_fleet / avg_fleet.sum()


        # Total fleet growth for this year
        growth = historic_population.loc[year, "new"]

        # Previous year's fleet totals
        previous_totals = df_result[previous_year]

        # Composition ratios for NEW vehicles entering the fleet
        composition_ratios = predicted_composition[year]

        # Number of new vehicles added for each type
        additions = growth * composition_ratios

        # Number of removed vehicles from each type
        total_exit = historic_population.loc[year, "implied_exit"]   
        if total_exit >= 0:

            remaining_exit = total_exit
            exiting_vehicles = pd.Series(
                0,
                index=previous_totals.index,
                dtype=float
            )

            available_types = previous_totals.index.tolist()

            while remaining_exit > 1e-8 and len(available_types) > 0:

                # Exit allocation based on original proportions
                weights = exit_proportions[available_types]

                weights = weights / weights.sum()

                proposed_exit = remaining_exit * weights

                # Cannot remove more vehicles than available
                actual_exit = pd.DataFrame({
                    "proposed": proposed_exit,
                    "available": previous_totals[available_types] - exiting_vehicles[available_types]
                }).min(axis=1)

                # Add this round of exits
                exiting_vehicles[available_types] += actual_exit

                # Remaining exits
                remaining_exit -= actual_exit.sum()

                # Remove vehicle types that have no vehicles left
                available_types = [
                    t for t in available_types
                    if previous_totals[t] - exiting_vehicles[t] > 1e-8
                ]

        else:
            exiting_vehicles = pd.Series(
                0,
                index=previous_totals.index
            )

        # New fleet totals
        new_totals = previous_totals + additions - exiting_vehicles

        df_result[year] = new_totals


    percentages = df_result.div(df_result.sum(axis=0), axis=1)
    for year in percentages.columns:
        output_df = pd.DataFrame(
            [percentages[year].values],
            index=[fsa_code],
            columns=percentages.index
        )
        output_path = DATA_DIR / "vehicles" / "predicted_share"/ f"fsa_vehicle_share_{year}_{SCN_CASE}.csv"
        if output_path.exists():
            output_df.to_csv(output_path, mode='a', header=False)
        else:
            output_df.to_csv(output_path, index_label="fsa")

    return df_result
