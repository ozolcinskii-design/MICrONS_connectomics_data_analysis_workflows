# MICrONS_connectomics_data_analysis_workflows
The **connectivity_plot()** class lets you:
1. Connect to cloud-based connectomics repositories via the CAVE infrastructure
2. Index and query available tables (data frames) for their meta data and contents such as cell IDs, cell types, connections and more.
3. Download and plot connectivity data of any cell group or type within the dataset.
4. Visualize selected cells in Neuroglancer <br><br>

## DOCUMENTATION
### ***connectivity_plot.initialize()*** <br>
connects to CAVE cloud architecture <br>
max_attempts (optional, int, default=3) - fallback for when server connection fails <br>
returns client, cv

### ***connectivity_plot.get_ids_by_ct(table_path)*** <br>
table_path (optional, str) - sources data frame locally<br>
table_name (optional, str) - sources data frame from server<br>
❗ One of the above must be provided<br>
table_path (required, str) - local dataframe

### ***connectivity_plot.materialize_connections(root_ids)*** <br>
root_ids (required, list) - cell IDs for which connections are to be sourced <br>
returns all_outputs, all_inputs

### ***connectivity_plot.assign_cell_types()*** <br>
table_path (optional, str) - sources data frame locally <br>
table_name (optional, str) - sources data frame from server <br>
❗ One of the above must be provided

### ***connectivity_plot.scrape_connectivity_data()*** <br>
table_path (optional, str) - sources data frame locally <br>
table_name (optional, str) - sources data frame from server <br>
❗ One of the above must be provided <br>
chunk_size (optional, int, default=3) - number of ids to scrape data for at a time <br>
max_workers (optional, int, default=4) max number of threads to run at a time

### ***connectivity_plot.get_top_partners_for_list()*** <br>
root_ids (required, list)<br>
all_outputs (required, ) - sourced from connectivity data; *see scrape_connectivity_data()* <br>
all_inputs - sourced from connectivity data; see *scrape_connectivity_data()* <br>
ct (optional, str, default=None) - cell type; only relevant for looped use, such as in *graph_ct_connectivity()* <br>
output_path (optional, str, default=working dir) - customizable path for saving graphs <br>
color (optional, str, default=None) - enables changing the colors of frequency lines on graph

### ***connectivity_plot.build_neuroglancer()*** - <br>
root_ids (required, list) - list of seg IDs to be loaded into visualization <br>
seg_source (required, str: static | dynamic) - sets type of segmentation to be loaded <br>
resolution (optional, list, default=[4, 4, 40]) - sets voxel dimensions

### ***connectivity_plot.require_connection()*** - helper function; fallback for when CAVEclient is not connected

### ***connectivity_plot.table_source_condition()*** - helper function; picking local or server source
---
<br>

# Example usage
```
import connectivity_plot
import pandas as pd

# UPDATE self.dir_path IN __init__ BEFORE YOU START
# Connect to cloud-based services
data = connectivity_plot.connectivity_plot()
client = data.initialize()
```

### Index available tables
```
def table_index():
    from pandasgui import show
    table_list = client.materialize.get_tables()
    rows = []
    for item in table_list:
        meta_data = client.materialize.get_table_metadata(item)
        row = {"table_name": item, **meta_data}
        rows.append(row)
    df = pd.DataFrame(rows)
    show(df)
    return
```

### Query and download table by name
IMPORTANT: do not download every table (e.g. in a loop) - tables containing synapse data can be 100s of millions of rows long.
Visit https://tutorial.microns-explorer.org/annotation-tables.html for reference.
```
from pandasgui import show
table_name = "YOUR_TABLE_NAME"
df = client.materialize.query_table(table_name, limit=100)
show(df)

client, cv = data.initialize()
def download_table(table_name):
    df = client.materialize.query_table(table_name)
    df.to_parquet(f'{table_name}')
```

### Download bulk connectivity data for cell types in table
```
table_path="saved_dataframes/TABLE_NAME_HERE.parquet"
data.scrape_connectivity_data(table_path)
```
### Generate aggregate connectivity graphs

x-axis >>> all individual synaptic partners of a neuron
y-axis >>> number of synapses a neuron makes with its synaptic partners

Each frequency line represents a single neuron and all its connections to other neurons, sorted from most to least, i.e.:
If frequency line of neuron n falls on x=100 and y=5, it means that it is connected by 5 synapses to 100 different neurons.
```
data.graph_ct_connectivity(table_path, output_path=None)
```

### Visualize cell type in Neuroglancer
```
table_name = "allen_column_mtypes_v2"
df = client.materialize.query_table(table_name)
cell_types = df['cell_type'].unique()
print(cell_types)
ct = 'YOUR_SELECTED_CELL_TYPE'
ct_df = df[df['cell_type'] == ct][['pt_root_id', 'cell_type']]
root_ids = ct_df['pt_root_id']
data.build_neuroglancer(client, root_ids, seg_source="static")
```
