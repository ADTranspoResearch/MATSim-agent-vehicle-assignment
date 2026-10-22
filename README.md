# MATSim-agent-vehicle-assignment
Module used for assigning vehicle make/model/year/type to agents of the
output of a MATSim simulation based on demographic and locational
variables.  
  

## MATSim data
module requires the output population file of a MATSim simulation.
Module will return a population file with an extra attribute containing
vehicle information for the given agent.  
  
  
## Vehicle data
Vehicle ownership information is required with either total number of
vehicles or proportion of owned vehicles for a given region. Demographic
data can also be used to inform vehicle assignment.  

sample_ownership.csv provides an example of the data format required by
the model. It is randomized and anonymized sample from a larger dataset
so should not be used as a source but only for testing.

## Local GUI platform

Run the local platform with:

```bash
python3 scripts/run_platform_gui.py
```

The GUI opens at `http://127.0.0.1:8765` by default. It provides an English
interface for configuring MATSim input files, selecting a vehicle composition
year/scenario, setting the vehicle assignment seed, writing an updated MATSim
vehicle file, and generating FSA research outputs. Research outputs include a
heatmap and the five highest-value FSAs for CO2 emissions or EV electricity
demand.

The platform can also run the portable MATSim emissions module from
`matsim-emissions`. Use **Run Emission Module** after creating or selecting an
assigned vehicle file. The platform writes a scenario-specific emission config
under `data/MATSim/emission_configs`, writes emission events under
`data/MATSim/emission_events/<year>_<scenario>/`, and then uses that emission
events file for CO2 outputs. This step requires Maven (`mvn`) on `PATH`.

The page has five tabs:

- **Pipeline**: configure inputs, assign vehicle types, run the emission module,
  generate CO2 and EV electricity maps for one run.
- **Explore**: map any indicator (EV share, CO2 per agent, kappa, demand
  density, charging load) for each scenario on a shared colour scale, the
  citywide results table, the adoption versus baseline-emissions scatter and
  the concentration curve.
- **What-if**: change the EV adoption rate (citywide factor, per-FSA override,
  boost the highest-emitting FSAs) and see results update live.
- **Policy**: equal-effort experiment. Add a fixed number of extra EVs and
  compare allocation rules (uniform, top-k by CO2 per agent, top-k by marginal
  effectiveness), what each EV replaces, and bounds on within-FSA assignment.
- **Priorities**: re-draw vehicle assignments many times and report which FSAs
  stay in the top-k on residual CO2, kappa and demand density.

The last four tabs use `platform_gui/whatif.py`, which builds an agent table
once (home FSA, simulated km per day, EV kWh/km) and then recomputes any fleet
composition in milliseconds. This is valid while travel demand and emission
factors are held fixed, as in the paper. Per-category g/km factors are
regressed from the reference emission events. Check the "About these numbers"
note on the Explore tab for the calibration error.

Tests: `python3 -m unittest discover -s tests`.

Default paths are stored in `platform_gui/default_config.json`. Changes saved
from the GUI are written to `platform_gui/config.json`, which is intentionally
kept separate from the default template.

Scenario identifiers are `bau`, `acc_adopt`, `del_adopt`, and `pol_align`. Assigned vehicle
files use `vehicles_<year>_<scenario>_seed<seed>.xml` in the GUI (for example,
`vehicles_2035_bau_seed1.xml`) and `vehicles_<year>_<scenario>.xml` in the CLI.
