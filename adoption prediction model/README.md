# Adoption Prediction Model

This folder has been reduced to the replacement-dynamics workflow only.

## What is kept

- `.cache/`
  Cached SAAQ datasets used by the notebooks.

- `datasets/`
  Local reference datasets used by the calibrated notebook:
  - [Fig1-NMVRegist.xlsx](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/datasets/Fig1-NMVRegist.xlsx)
  - [1710000901-eng.csv](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/datasets/1710000901-eng.csv)

- `notebooks/`
  Current working notebooks:
  - [replacement_dynamics_ev_calibrated_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_ev_calibrated_model.ipynb)
  - [fsa_replacement_dynamics_ev_calibrated_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/fsa_replacement_dynamics_ev_calibrated_model.ipynb)
  - [model_validation_2025.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/model_validation_2025.ipynb)

- `validation_outputs/`
  Current working outputs:
  - [replacement_dynamics_ev_calibrated_model](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/replacement_dynamics_ev_calibrated_model)
  - [fsa_replacement_dynamics_ev_calibrated_model](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/fsa_replacement_dynamics_ev_calibrated_model)
  - [model_validation_2025](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/model_validation_2025)
  - [recalibrated_sales_share_forecast](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/recalibrated_sales_share_forecast)
  - [fsa_model_validation_2025](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/fsa_model_validation_2025)
  - [replacement_dynamics_presentation](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/replacement_dynamics_presentation)

## Recommended reading order

1. [replacement_dynamics_ev_calibrated_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_ev_calibrated_model.ipynb)
   Province-level calibrated replacement-dynamics model using the external Quebec registrations data and population-linked fleet growth.

2. [fsa_replacement_dynamics_ev_calibrated_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/fsa_replacement_dynamics_ev_calibrated_model.ipynb)
   FSA-level calibrated version with hierarchical shrinkage toward the province benchmark.

3. [model_validation_2025.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/model_validation_2025.ipynb)
   Honest validation notebook comparing the model against observed Quebec adoption data from 2021 to 2025.

4. [replacement_dynamics_presentation](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/replacement_dynamics_presentation)
   Presentation-ready figures and PowerPoint outputs summarizing the current workflow.

## Cache files

The notebooks rely mainly on:

- `saq_vehicle_counts.pkl`
- `saq_entry_counts.pkl`
- `saq_entry_full.pkl`

Other cache files were left in place rather than regenerated, but the working replacement-dynamics notebooks are centered on the three files above.
