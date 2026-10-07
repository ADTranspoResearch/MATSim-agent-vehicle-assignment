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

Default paths are stored in `platform_gui/default_config.json`. Changes saved
from the GUI are written to `platform_gui/config.json`, which is intentionally
kept separate from the default template.
