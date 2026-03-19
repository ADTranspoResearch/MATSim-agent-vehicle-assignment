"""
Module contains functions for parsing and analyzing MATSim population.
"""

import pandas as pd
import geopandas as gpd
import xml.etree.ElementTree as ET
from shapely import Point


def get_demos(person: ET.Element):
    """
    Takes a "person" XML tree as input and returns gender and age.

    :param person: XML Element of person from population file.

    Returns (gender, age) (string, int)
    """

    try:
        sex_elem = person.find("./attributes/attribute[@name='sex']")
        gender = sex_elem.text.upper() if sex_elem is not None else None
        # Convert gender to french
        if gender == "1":
            gender = "F"
        else:
            gender = "H"

        age = 40  # TODO: Find mapping for age range in quebec data

    except KeyError as e:
        raise (
            KeyError(
                f"Agent {person.find("./attributes/attribute[@name='sex']")} does not gender and/or age."
            )
        ) from e

    return (gender, age)


def get_home(person: ET.Element):
    """
    Takes a "person" XML tree as input and returns home XY coord.

    :param person: XML Element of person from population file.

    Returns (X,Y)
    """

    plan = person.find("plan")
    found_home = False
    for activity in plan.findall(".//activity"):
        # Only looking for first home based activity.
        if activity.get("type") == "home":
            xy = (float(activity.get("x")), float(activity.get("y")))
            found_home = True
            break
    if found_home:
        return xy
    else:
        raise (
            KeyError(f"Agent {person.get('id')} does not have home activity in plan.")
        )


def get_fsa_table(root):
    """
    Reads the FSA lookup table, if it does not exist, builds it and
    saves it.

    :param root: the population file xml tree containing users. Used
    for building the FSA table if it does not exist.

    Returns fsa_df lookup table with user_id as index and FSA in other
    Column.
    """

    try:
        fsa_table = pd.read_csv(
            "FSA/agent_id_fsa_table.csv",
            index_col=0,
        )
        fsa_table.index = fsa_table.index.astype(str)
    except FileNotFoundError:
        print("No agent_fsa table found, generating table")
        fsa_table = build_fsa_table(root)
    return fsa_table


def build_fsa_table(root: ET.ElementTree):
    """
    Creates a table containing user IDs and home FSA location.

    If a lookup table has not already been created, this function will
    generate it and then save it to a file so that it can be read
    instead of rebuilding it each time.

    :param root: the population file xml tree containing users.

    Returns fsa_df lookup table with user_id as index and FSA in other
    Column.
    """

    # TODO: implement CRS selection
    home_dict = {
        person.get("id"): Point(get_home(person)) for person in root.iter("person")
    }
    home_gdf = gpd.GeoDataFrame(
        {"geometry": list(home_dict.values())},
        index=list(home_dict.keys()),
        geometry="geometry",
        crs="EPSG:32187",
    )
    province_fsa_gdf = gpd.read_file("FSA/quebec_fsa/quebec_fsa.shp")

    province_fsa_gdf = province_fsa_gdf.to_crs(home_gdf.crs)

    joined = gpd.sjoin(home_gdf, province_fsa_gdf, how="left", predicate="intersects")
    fsa_df = joined["CFSAUID"].drop(columns="geometry")
    fsa_df.to_csv("FSA/agent_id_fsa_table.csv")
    return fsa_df
