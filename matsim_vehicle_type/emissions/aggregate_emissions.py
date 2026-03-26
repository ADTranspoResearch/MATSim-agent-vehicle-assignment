from collections import defaultdict

import matsim
import pandas as pd

from matsim_vehicle_type.config import DATA_DIR


def aggregate_emissions(events_file: str, aggregate: str = "vehicle") -> pd.DataFrame:
    """
    Reads the emissions from a MATSim events file
    and aggregates them by specification.
    Parameters
    ----------
    events_file : str
        Path to the MATSim events file. Should be relative to root folder.
    aggregate : str, optional
        The aggregation level for the emissions data. Default is 'vehicle'.

    Returns
    -------
    pd.DataFrame
        A DataFrame containing the aggregated emissions data.
    """
    # Read the events and sum up all emissions, create a df.
    events = matsim.event_reader(events_file, types="warmEmissionEvent")
    emission_dict = defaultdict(float)
    for _ ,event in enumerate(events):
        emission_dict[event[f"{aggregate}Id"]] += float(event["CO2"])

    emission_df = pd.DataFrame.from_dict(emission_dict, orient="index", columns=["co2"])

    # Add FSA to each vehicle (agent) ID.
    fsa_table_path = DATA_DIR / "FSA" / "agent_id_fsa_table.csv"
    fsa_table = pd.read_csv(fsa_table_path, index_col=0)
    fsa_table.index = fsa_table.index.astype(str)
    emission_df = emission_df.merge(fsa_table, how="left", left_index=True, right_index=True)
    return emission_df
