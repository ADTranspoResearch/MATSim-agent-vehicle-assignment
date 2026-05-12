import _setup_path  # pylint: disable=unused-import

import pandas as pd

from matsim_vehicle_type.fleet.main import main
from matsim_vehicle_type.fleet.growth import predict_fleet_over_time
from matsim_vehicle_type.fleet.composition import (
    historic_fleet_composition,
    get_growth_trends,
    predict_composition_trend,
)
from matsim_vehicle_type.config import DATA_DIR

historic_pop = main()

fleet_path = DATA_DIR / "vehicles" / "ownership" / "personal_ownership"
dtype_map = {
    "MOD": "string",
    "CYL2": "string",
    "CARB": "string",
    "Motorisation": "string",
    "Genre": "string",
    "Hybrid Type": "string",
    "Propulsion": "string",
}
historic_comp_dfs = []
for i in range(2013, 2021):
    filename = f"Personal_McGill_SAAQ_{i}_2024-01-10.csv"
    filepath = fleet_path / filename
    print(f"running {filename}.")
    df_year = pd.read_csv(filepath, dtype=dtype_map)
    composition = historic_fleet_composition(df_year)
    historic_comp_dfs.append(composition)


print(historic_comp_dfs)
avg_type_growth = get_growth_trends(historic_comp_dfs)


initial_composition = (
    historic_comp_dfs[-1].set_index("vehicle_type")["count"]
    / historic_comp_dfs[-1]["count"].sum()
).to_dict()

prediction = predict_composition_trend(
    initial_composition, avg_type_growth, end_year=2041
)

prediction.to_csv("new_vehicle_composition_ratios.csv")

predicted_fleet = predict_fleet_over_time(
    historic_comp_dfs[-1], historic_pop, prediction
)
