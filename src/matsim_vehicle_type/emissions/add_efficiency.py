import pandas as pd

from matsim_vehicle_type.config import SCN_YEAR
def add_efficiency(emission_df:pd.DataFrame, efficiency_df:pd.DataFrame)-> pd.DataFrame:
    """
    Adds an efficiency column to the emissions dataframe,
    which is the percent improvement of emissions output for given year.
    
    Parameters
    ----------
    emission_df : pd.DataFrame
        A DataFrame containing the emissions data, with a column for FSA.
    efficiency_df : pd.DataFrame
        A DataFrame containing the efficiency data, with columns for FSA,
        year and efficiency.
    
    Returns
    -------
    pd.DataFrame
        A modified emissions_df with agent emissions adjusted by FSA efficiency.
    """

    efficiency_df = efficiency_df["predicted_improvement_pct"].loc[efficiency_df["AnneeSAAQ"] == SCN_YEAR]
    emission_df = emission_df.join(efficiency_df, on="FSA", how="left")
    emission_df["co2"] = emission_df["co2"] * emission_df["predicted_improvement_pct"]
    