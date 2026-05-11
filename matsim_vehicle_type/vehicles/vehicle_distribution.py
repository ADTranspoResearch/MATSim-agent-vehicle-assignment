"""
Module used to read vehicle ownership file and return per-FSA vehicle
type distributions for a given year. 
"""

import pandas as pd

from matsim_vehicle_type.config import DATA_DIR


def get_vehicle_type(row: pd.Series) -> str:
    """
    Takes the data of a vehicle ownership row and returns the vehicle
    type to be assigned to that row.

    Determines vehicle type based on the engine (ice, electric, hybrid)
    the size based on the vehicle classification and then returns the
    matching vehicle type, or "unknow"

    Parameters
    ----------
    row : pd.Series
        Entire row of the vehicle ownership dataset. Should contain
        engine type information, vehicle size classification information
        and hybrid information.

    Returns
    -------
    str
        assigned vehicle type code
    """
    h_type = str(row.get("Hybrid Type")).lower().strip()
    motor = str(row.get("Motorisation", "")).lower().strip()
    c_main = str(row.get("Classe principale", "")).lower().strip()

    is_sedan = any(
        x in c_main
        for x in [
            "compacte",
            "sous-sompacte",
            "intermediaire",
            "minicompacte",
            "grande berline",
            "deux places",
        ]
    )
    is_suv = any(x in c_main for x in ["familiale", "fourgonnette", "vus"])
    is_pickup_van = any(
        x in c_main for x in ["camionnette", "vehicule à usage spécial", "fourgon"]
    )

    if h_type == "" and motor == "":
        return "unknow"
    if motor == "electrique":
        return "electric"

    is_hybrid = (motor in ["hybride", "hybride branchable"]) or (
        motor == "" and h_type != ""
    )
    is_icev = motor in ["diesel", "essence", "gaz naturel"]

    if is_hybrid:
        if is_suv:
            return "hev_suv"
        if is_sedan:
            return "hev_sedan"
        if is_pickup_van:
            return "hev_van/pickup"

    elif is_icev:
        if is_pickup_van:
            return "ice_van/pickup"
        if is_suv:
            return "ice_suv"
        if is_sedan:
            return "ice_sedan"


def build_vehicle_distribution(
    year, vehicle_ownership_path: str, to_file: bool = True
) -> pd.DataFrame:
    """
    Calculates the per-FSA vehicle ownership distribution for a
    given vehicle ownership dataset.

    Returns & optionally saves the FSA distributions as a DataFrame to
    a file.

    Parameters
    ----------
    year : int
        Year of the desired distribution.
    vehicle_ownership_path : str
        Relative path to the vehicle ownership files.
    to_file : bool, optional
        If true, will save the distributions to a file, by default True

    Returns
    -------
    pd.DataFrame
        Vehicle type distributions sorted by FSA.
    """

    df = (
        pd.read_csv(vehicle_ownership_path, sep=";", encoding="utf-16")
        .loc[
            :,
            [
                "RTA",
                "Hybrid Type",
                "Motorisation",
                "Classe principale",
                "Usage",
            ],
        ]
        .rename(columns={"RTA": "fsa"})
        .query("Usage != 'Commercial'")
        .dropna(subset=["Classe principale"])
        .drop(columns=["Usage"])
        .copy()
    )

    df["vehicle_type"] = df.apply(get_vehicle_type, axis=1)
    df = df.drop(columns=["Hybrid Type", "Motorisation", "Classe principale"]).query(
        "vehicle_type != 'hev_van/pickup' and vehicle_type != 'unknow'"
    )

    veh_dist = (
        df.groupby(["fsa"])["vehicle_type"]
        .value_counts(normalize=True)
        .reset_index(name="proportion")
    )

    pivot_veh_dist = veh_dist.pivot_table(
        index=["fsa"],
        columns="vehicle_type",
        values="proportion",
        fill_value=0,
    )
    pivot_veh_dist = pivot_veh_dist.sort_index()

    if to_file:
        output_path = DATA_DIR / "vehicles" / f"fsa_vehicle_share_{year}"
        print(f"Saving vehicle distribution to {output_path}")
        pivot_veh_dist.to_parquet(output_path.with_suffix(".parquet"))
    return pivot_veh_dist
