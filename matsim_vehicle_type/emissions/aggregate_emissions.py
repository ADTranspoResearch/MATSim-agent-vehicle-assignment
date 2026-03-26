import matsim
import pandas as pd
from collections import defaultdict

from matsim_vehicle_type.config import DATA_DIR
def aggregate_emissions(events_file: str, aggregate: str = 'vehicle') -> pd.DataFrame:
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
    for event in events:
        emission_dict[event[aggregate]] += event["co2"]
    emission_df = pd.DataFrame.from_dict(emission_dict, orient="index", columns=["co2"])

    # Add FSA to each vehicle (agent) ID.
    fsa_table_path = DATA_DIR / "FSA" / "agent_id_fsa_table.csv"
    fsa_table = pd.read_csv(fsa_table_path, index_col=0)
    emission_df = emission_df.join(fsa_table, how='left')
    return emission_df