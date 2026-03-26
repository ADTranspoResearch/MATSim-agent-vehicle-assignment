import pandas as pd
import _setup_path #pylint: disable=unused-import
from matsim_vehicle_type.config import MATSIM_DIR, DATA_DIR
from matsim_vehicle_type.emissions.aggregate_emissions import aggregate_emissions
from matsim_vehicle_type.emissions.add_efficiency import add_efficiency

emissions_path = MATSIM_DIR / "emissions" / "outputemission.events.offline.xml.gz"
efficiency_path = DATA_DIR / "vehicles" / "tc_improvement_all_fsa.csv"
efficiency_df = pd.read_csv(efficiency_path)
emissions_df = aggregate_emissions(emissions_path)
emissions_df = add_efficiency(emissions_df, efficiency_df)

