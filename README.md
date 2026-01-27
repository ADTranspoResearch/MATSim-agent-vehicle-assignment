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