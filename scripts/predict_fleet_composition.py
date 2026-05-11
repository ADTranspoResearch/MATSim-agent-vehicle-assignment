
import _setup_path  # pylint: disable=unused-import

import pandas as pd

from matsim_vehicle_type.fleet.main import main
from matsim_vehicle_type.fleet.composition import historic_fleet_composition, get_growth_trends, predict_composition_trend
from matsim_vehicle_type.config import DATA_DIR

historic_pop = main()

fleet_path = DATA_DIR / "vehicles" / "ownership" / "personal_ownership"
dtype_map = {
    "MOD": "string",
    "CYL2":"string",
    "CARB": "string",
    "Motorisation":"string",
    "Genre": "string",
    "Hybrid Type" : "string",
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



initial_composition = (historic_comp_dfs[-1].set_index("vehicle_type")["count"] /historic_comp_dfs[-1]["count"].sum() ).to_dict()

prediction = predict_composition_trend(initial_composition, avg_type_growth, end_year=2041)

prediction.to_csv("fleet_prediction.csv")

# Predict fleet change over time

base_counts = historic_comp_dfs[-1].set_index("vehicle_type")["count"]

# Create output dataframe
result_df = pd.DataFrame(index=base_counts.index)

# Store initial year (2020)
result_df[2020] = base_counts

# Ensure prediction years are sorted numerically
prediction_years = sorted(prediction.columns)

for year in prediction_years:

    previous_year = year - 1

    # Total fleet growth for this year
    growth = historic_pop.loc[year, "fleet_growth"]

    # Previous year's fleet totals
    previous_totals = result_df[previous_year]

    # Composition ratios for NEW vehicles entering the fleet
    composition = prediction[year]

    # Number of new vehicles added for each type
    additions = growth * composition

    # New fleet totals
    result_df[year] = previous_totals + additions

result_df.to_csv("predicted_fleet_composition.csv")

print(result_df)