from pathlib import Path

import pandas as pd
from matsim_vehicle_type.config import DATA_DIR
from matsim_vehicle_type.emissions.aggregate_emissions import aggregate_emissions
from matsim_vehicle_type.emissions.add_efficiency import add_efficiency
emission_filename = "filename.xml"
emissions_events_path = DATA_DIR / "emissions" / emission_filename

efficiency_filename = "tc_improvement_all_fsa.csv"
efficiency_path = DATA_DIR / "emissions"/ efficiency_filename

efficiency_df = pd.read_csv(efficiency_path)


emissions_df = aggregate_emissions(emissions_events_path, aggregate="vehicle")

predicted_emissions_df = add_efficiency(emissions_df, efficiency_df)
