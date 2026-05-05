import connectivity_plot
from pandasgui import show
import pandas as pd

data = connectivity_plot()

client, cv = data.initialize()


data.scrape_connectivity_data(table_path="saved_dataframes/proofreading_status_and_strategy/proofreading_status_and_strategy.parquet")

data.graph_ct_connectivity(table_path="saved_dataframes/proofreading_status_and_strategy/proofreading_status_and_strategy.parquet")


