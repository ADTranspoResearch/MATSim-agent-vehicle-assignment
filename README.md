# MATSim-agent-vehicle-assignment

Code for projecting neighborhood-level vehicle fleets and assigning
vehicle types to MATSim agents, used in the study *"Spatially targeted
electric vehicle adoption: Linking neighborhood fleets, emissions, and
electricity demand"* (Quebec City case study, prepared for submission to
*Transportation Research Part D: Transport and Environment*; an earlier
version was prepared for the TRB Annual Meeting).

The pipeline models vehicle stocks and technology shares at the Forward
Sortation Area (FSA) level from SAAQ registration and census population
data, projects them through 2040 under four electrification pathways
(business-as-usual, accelerated, delayed, policy-aligned), and writes
scenario-specific vehicle types back into MATSim vehicle files so that
emissions and EV electricity demand can be evaluated per agent and per
neighborhood.

## Repository layout

- `adoption prediction model/`
  Replacement-dynamics fleet model notebooks (province- and FSA-level),
  plus validation notebooks comparing the calibrated model against
  observed Quebec adoption for 2021--2025 (`notebooks/`,
  `validation_outputs/`). See the folder README for the recommended
  reading order.

- `matsim_vehicle_type/`
  Python package implementing the pipeline:
  - `fleet/` -- population-driven fleet growth, turnover, and
    composition projection (`growth.py`, `composition.py`, `main.py`)
  - `population/` -- MATSim population parsing and FSA assignment
  - `vehicles/` -- vehicle-distribution construction and probabilistic
    agent-vehicle assignment
  - `config.py` -- paths, scenario cases, and dtype maps

- `scripts/`
  Entry points, in pipeline order:
  1. `create_personal_vehicle_dataset.py` -- build the personal-vehicle
     dataset from SAAQ registration files
  2. `create_prediction_dataset.py` -- prepare the model input dataset
  3. `predict_fleet_composition.py` -- project FSA fleet size and
     composition through 2040 under the scenario set
  4. `create_vehicle_distribution.py` -- convert projections into
     FSA-level vehicle-type probability distributions
  5. `run_vehicle_assignment.py` -- sample a vehicle type for each
     MATSim agent conditional on its home FSA and write the updated
     MATSim vehicle file

- `data/`, `output/`
  Local input and output folders. The SAAQ vehicle-registration
  microdata and the full MATSim scenario files are **not** included in
  this repository (see Data below); `.gitignore` excludes them.

## Data

The SAAQ vehicle-registration microdata were obtained under a
data-sharing agreement with the Société de l'assurance automobile du
Québec and cannot be redistributed. Population data come from the 2021
Census of Population (Statistics Canada) and the Institut de la
statistique du Québec population projections. The MATSim Quebec City
scenario is described in Manzolli et al. (2026), *Applied Energy* 413,
127735 (doi:10.1016/j.apenergy.2026.127735).

## Citation

See [CITATION.cff](CITATION.cff). Please cite the journal article once
published; until then, cite the repository.

## License

GPL-3.0 (see [LICENSE](LICENSE)).
