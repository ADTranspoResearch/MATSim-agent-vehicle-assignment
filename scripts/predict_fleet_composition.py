import _setup_path  # pylint: disable=unused-import

import pandas as pd

from matsim_vehicle_type.fleet.main import main
from matsim_vehicle_type.fleet.growth import predict_fleet_over_time
from matsim_vehicle_type.fleet.composition import (
    historic_fleet_composition,
    get_growth_trends,
    predict_composition_trend,
)
from matsim_vehicle_type.config import DATA_DIR, PC_QC, DTYPE_MAP, SCN_CASE, PC_QCP
from collections import defaultdict

fleet_path = DATA_DIR / "vehicles" / "ownership" / "personal_ownership"

fleet_by_fsa_year = defaultdict(dict)   # fleet_by_fsa_year[fsa][year] = df
entrant_by_fsa_year = defaultdict(dict)

for i in range(2013, 2021):
    filename = f"Personal_McGill_SAAQ_{i}_2024-01-10.csv"
    filepath = fleet_path / filename
    print(f"Loading {filename}...")

    df_year = pd.read_csv(filepath, dtype=DTYPE_MAP)
    # df_filtered = df_year[df_year['RTA'].isin(PC_QC)]
    for fsa_code, group in df_year.groupby('RTA'):
        fleet_by_fsa_year[fsa_code][i] = group.copy()
    
    df_entrant = df_year.loc[df_year["Entrant"].eq(1)].copy()

    for fsa_code, group in df_entrant.groupby('RTA'):
        entrant_by_fsa_year[fsa_code][i] = group.copy()

    del df_year, df_entrant


total_fleet = pd.DataFrame()

# PC_QC: lists of PC of Quebec City
# PC_QCP: lists of PC of Quebec Province
# {"H0H"}: PC representing the whole province, used for province-level prediction
# Q0Q: PC representing the whole city, used for city-level prediction

for fsa_code in PC_QC:
    print(f"-------------Prediction for {fsa_code} starts-------------")
    historic_pop = main(fsa_code)

    historic_comp_dfs = []

    historic_entrant_comp_dfs = []

    for i in range(2013, 2021):
        if fsa_code == "H0H":
            df_list = [
                fleet_by_fsa_year[fsa].get(i) 
                for fsa in PC_QCP 
                if fsa in fleet_by_fsa_year
            ]
            df_year = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
            df_entrant_list = [
                entrant_by_fsa_year[fsa].get(i) 
                for fsa in PC_QCP 
                if fsa in entrant_by_fsa_year
            ]
            df_entrant_year = pd.concat(df_entrant_list, ignore_index=True) if df_entrant_list else pd.DataFrame()

        elif fsa_code == "Q0Q":
            df_list = [
                fleet_by_fsa_year[fsa].get(i) 
                for fsa in PC_QC 
                if fsa in fleet_by_fsa_year
            ]
            df_year = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
        else:
            df_year = fleet_by_fsa_year[fsa_code].get(i)
            df_entrant_year = entrant_by_fsa_year[fsa_code].get(i)

        if df_year is None:
            continue
        composition = historic_fleet_composition(df_year)
        historic_comp_dfs.append(composition)
        entrant_composition = historic_fleet_composition(df_entrant_year)
        historic_entrant_comp_dfs.append(entrant_composition)

    # avg_type_growth = get_growth_trends(historic_entrant_comp_dfs)
    avg_type_growth = get_growth_trends(historic_comp_dfs)

    initial_composition = (
        historic_entrant_comp_dfs[-1].set_index("vehicle_type")["count"]
        / historic_entrant_comp_dfs[-1]["count"].sum()
    ).to_dict()
    # initial_composition = (
    #     historic_comp_dfs[-1].set_index("vehicle_type")["count"]
    #     / historic_comp_dfs[-1]["count"].sum()
    # ).to_dict()    

    # Predicted composition of newly registered vehicles
    pred_new_veh_mix = predict_composition_trend(
        initial_composition, avg_type_growth, end_year=2051
    )
    

    pred_yearly_fleet = predict_fleet_over_time(
        historic_comp_dfs, historic_pop, pred_new_veh_mix, fsa_code
    )

    # ---------- Saved as validation output files ---------- 
    save_dir = DATA_DIR / "vehicles" / "val_outputs" / SCN_CASE
    save_dir.mkdir(parents=True, exist_ok=True)

    csv_path = save_dir / f"{fsa_code}_predicted_fleet_mix.csv"
    percentages = pred_yearly_fleet.div(pred_yearly_fleet.sum(axis=0), axis=1)
    print(f"Predicted fleet mix for {fsa_code}:\n{percentages}")
    pred_yearly_fleet.to_csv(csv_path)

    with open(csv_path, mode="a", encoding="utf-8") as f:
        f.write("\n# ---------- Fleet Share Percentages ----------\n")
        percentages.to_csv(f)
        f.write("\n# ---------- Predicted New Vehicle Mix ----------\n")
        pred_new_veh_mix.to_csv(f)
    print(f"validation output saved for {fsa_code}.")
    # ------------------------------------------------------ 


    # for city-level predictions
    # if total_fleet is None:
    #     total_fleet = pred_yearly_fleet.copy()
    # else:
    #     total_fleet = total_fleet.add(pred_yearly_fleet, fill_value=0)




# QC_save_path = save_dir / f"QC_predicted_fleet_mix_{SCN_CASE}.csv"
# total_fleet.to_csv(QC_save_path)

print("-------------Prediction for all fsa finished-------------")
