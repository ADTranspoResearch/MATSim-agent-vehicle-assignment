# Adoption Prediction Model

This folder now contains one clean prediction workflow with only two notebooks:

- [province_prediction_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/province_prediction_model.ipynb)
- [fsa_prediction_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/fsa_prediction_model.ipynb)

## Folder Structure

- `.cache/`
  Heavy cached SAAQ files used by the model.

- `datasets/`
  External reference files used by the calibrated model:
  - [Fig1-NMVRegist.xlsx](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/datasets/Fig1-NMVRegist.xlsx)
  - [1710000901-eng.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/datasets/1710000901-eng.csv)

- `src/prediction_model/`
  Shared code used by both notebooks:
  - `config.py`
  - `data.py`
  - `province.py`
  - `fsa.py`

- `notebooks/`
  The two entry points for running the model.

- `outputs/`
  Saved model outputs:
  - `outputs/province/`
  - `outputs/fsa/`

## How To Use

1. Open [province_prediction_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/province_prediction_model.ipynb) for the provincial forecast.
2. Open [fsa_prediction_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/fsa_prediction_model.ipynb) for the FSA forecast.
3. In either notebook, change:
   - `FORECAST_END_YEAR`
   - `SELECTED_YEAR`
4. In the FSA notebook, you can also change:
   - `TARGET_FSA`

The notebooks save the full yearly outputs automatically.

## Main Output Files

Province:
- [sales_share_by_year.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/outputs/province/sales_share_by_year.csv)
- [fleet_share_by_year.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/outputs/province/fleet_share_by_year.csv)
- [vehicle_counts_by_year.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/outputs/province/vehicle_counts_by_year.csv)

FSA:
- [fsa_sales_share_by_year.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/outputs/fsa/fsa_sales_share_by_year.csv)
- [fsa_fleet_share_by_year.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/outputs/fsa/fsa_fleet_share_by_year.csv)
- [fsa_vehicle_counts_by_year.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/outputs/fsa/fsa_vehicle_counts_by_year.csv)
