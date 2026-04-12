# Adoption Prediction Model

This folder has been reduced to the replacement-dynamics workflow only.

## What is kept

- `.cache/`
  Cached SAAQ datasets used by the notebooks.

- `notebooks/`
  The replacement-dynamics notebooks:
  - [replacement_dynamics_adoption_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_adoption_model.ipynb)
  - [replacement_dynamics_adoption_model_fsa.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_adoption_model_fsa.ipynb)
  - [replacement_dynamics_entry_exit_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_entry_exit_model.ipynb)
  - [replacement_dynamics_ev_calibrated_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_ev_calibrated_model.ipynb)
  - [replacement_dynamics_ev_population_scenarios.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_ev_population_scenarios.ipynb)

- `validation_outputs/`
  Outputs produced by the replacement-dynamics notebooks:
  - [replacement_dynamics_adoption_model](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/replacement_dynamics_adoption_model)
  - [replacement_dynamics_adoption_model_fsa](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/replacement_dynamics_adoption_model_fsa)
  - [replacement_dynamics_entry_exit_model](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/replacement_dynamics_entry_exit_model)
  - [replacement_dynamics_presentation](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/validation_outputs/replacement_dynamics_presentation)

## Recommended reading order

1. [replacement_dynamics_adoption_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_adoption_model.ipynb)
   Province-level replacement model using smooth fleet change and projected sales share.

2. [replacement_dynamics_adoption_model_fsa.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_adoption_model_fsa.ipynb)
   The same logic applied to FSAs, with local diagnostics.

3. [replacement_dynamics_entry_exit_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_entry_exit_model.ipynb)
   The stricter version that models entries and disposals separately year by year using `Entrant`/`Neuf` and `Sortant`.

4. [replacement_dynamics_ev_calibrated_model.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_ev_calibrated_model.ipynb)
   The replacement model with the full future entry-share mix calibrated from external quarterly new-vehicle registrations, 2017 to 2025 Q1, and total fleet growth linked to the Quebec population reference.

5. [replacement_dynamics_ev_population_scenarios.ipynb](/Users/natomanzolli/Documents/GitHub/MATSim-agent-vehicle-assignment/adoption prediction model/notebooks/replacement_dynamics_ev_population_scenarios.ipynb)
   The EV-calibrated replacement model with total-fleet trajectories linked to Quebec population projection scenarios instead of a simple linear fleet-growth assumption.

## Cache files

The notebooks rely mainly on:

- `saq_vehicle_counts.pkl`
- `saq_entry_counts.pkl`
- `saq_entry_full.pkl`

Other cache files were left in place rather than regenerated, but the working replacement-dynamics notebooks are centered on the three files above.
