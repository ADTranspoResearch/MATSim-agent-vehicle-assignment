import pandas as pd
import _setup_path #pylint: disable=unused-import
from matsim_vehicle_type.config import SCN_YEAR, DATA_DIR, ROOT

prediction_path = ROOT / "adoption prediction model" / "validation_outputs" / "replacement_dynamics_adoption_model_fsa" / "fsa_replacement_dynamics_market_share.csv"

all_predict_df = pd.read_csv(prediction_path)

scn_year_predict_df = all_predict_df.loc[all_predict_df["AnneeSAAQ"] == SCN_YEAR]

output_path = DATA_DIR / "vehicles" / f"fsa_vehicle_share_{SCN_YEAR}.csv"
scn_year_predict_df = scn_year_predict_df.drop(axis=1, columns="AnneeSAAQ")
scn_year_predict_df.to_csv(output_path, index=False)