import time
from caveclient import CAVEclient
from cloudvolume import CloudVolume
import threading
import pandas as pd
import os
from nglui import statebuilder
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor, as_completed

class connectivity_plot:
    def __init__(self):
        self.client = None
        self.cv = None
        self.lock = threading.RLock()
        self.mesh_source = None
        self.datastack_name = None
        self.root_ids = []
        self.viewer = None
        self.table_path = None

# ---------------------------------------------- DATA ACCESS ---------------------------------------------------

    def initialize(self, max_attempts=3):
        datastack_name = "minnie65_public"
        mesh_source = "precomputed://gs://iarpa_microns/minnie/minnie65/seg_m1300"
        for attempt in range(max_attempts):
            try:
                print(f"[Loading] Attempt {attempt + 1}/{max_attempts}: Connecting to {datastack_name}...")
        # Initialize CAVEclient
                print(f"  → Initializing CAVEclient...")
                self.client = CAVEclient(
                    server_address="https://global.daf-apis.com",
                    datastack_name=datastack_name
                )
        # Test authentication
                print(f"  → Authenticating...")
                self.client.info.get_datastack_info()
                
                print(f"  → Initializing CloudVolume...")
                self.cv = CloudVolume(mesh_source, use_https=True)
                
                print("[✓] CAVEclient and CloudVolume initialized successfully")
                return self.client, self.cv
            except Exception as exc:
                print(f"[✗] Initialization attempt {attempt + 1} failed:")
                last_error = str(exc)
                if "auth" in last_error.lower() or "token" in last_error.lower():
                    auth_msg = (
                        "Make sure you entered a valid API token in the box below"
                    )
                    print(auth_msg)
                    if attempt == max_attempts - 1:
                        raise RuntimeError(f"Authentication Error: {auth_msg}")
                time.sleep(2)
        raise RuntimeError(f"Failed to initialize CAVEclient or CloudVolume after {max_attempts} attempts.")


# ---------------------------------------------- DATA QUERIES --------------------------------------------------

    def get_ids_by_ct(table_path):
        df = pd.read_parquet(table_path)
        print(df['cell_type'].unique())
        ct = input("Choose cell type to return: ")
        root_ids = df[df['pt_root_id']['cell_type'] == ct].tolist()
        return root_ids

    def materialize_connections(self, root_ids):
        self.require_connection()
        all_outputs = self.client.materialize.synapse_query(pre_ids=root_ids)
        output_count = len(all_outputs)
        print(f"Successfully loaded all {output_count} outputs")
        all_inputs = self.client.materialize.synapse_query(post_ids=root_ids)
        input_count = len(all_inputs)
        print(f"Successfully loaded all {input_count} inputs")
        return all_outputs, all_inputs

    def assign_cell_types(self, table_path):
        ct_predictions = pd.read_parquet("saved_dataframes/raw_tables/aibs_metamodel_mtypes_v661_v2.parquet")
        df = pd.read_parquet(table_path)
        root_ids = df['pt_root_id'].tolist()
        matched_df = ct_predictions[ct_predictions['pt_root_id'].isin(root_ids)]
        ct_df = matched_df[['pt_root_id', 'cell_type']].copy()
        return ct_df

    def scrape_connectivity_data_by_ct(self, ct, df, chunk_size=50):
        self.require_connection()
        root_ids = df[df['cell_type'] == ct]['pt_root_id'].tolist()
        print(f"[{ct}] Scraping {len(root_ids)} cells...")
        
        all_outputs = []
        all_inputs = []

        for i in range(0, len(root_ids), chunk_size):
            chunk = root_ids[i : i + chunk_size]
            all_outputs.append(self.client.materialize.synapse_query(pre_ids=chunk))
            all_inputs.append(self.client.materialize.synapse_query(post_ids=chunk))

        if all_outputs:
            final_outputs = pd.concat(all_outputs, ignore_index=True)
            final_outputs.to_parquet(f'saved_dataframes/outputs_{ct}.parquet')
            
        if all_inputs:
            final_inputs = pd.concat(all_inputs, ignore_index=True)
            final_inputs.to_parquet(f'saved_dataframes/inputs_{ct}.parquet')

        return f"[{ct}] Finished! Saved {len(final_outputs) if all_outputs else 0} outputs."

    def scrape_data_threaded(self, table_path, chunk_size=50, max_workers=4):
        self.require_connection()
        df = self.assign_cell_types(table_path)
        cell_types = df['cell_type'].unique()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            active_tasks = {} 
            for ct in cell_types:
                job = executor.submit(self.scrape_connectivity_data_by_ct, ct, df, chunk_size)
                active_tasks[job] = ct
            for finished_job in as_completed(active_tasks):                
                ct = active_tasks[finished_job]
                try:
                    result_message = finished_job.result()
                    print(result_message)
                except Exception as exc:
                    print(f"[{ct}] generated an exception: {exc}")


# ---------------------------------------------- DATA ANALYSIS -------------------------------------------------
    def add_connectivity_line(self, synapse_counts, label='test', color=None):
        """
        Adds a frequency line (distribution) to the current active plot.
        
        Args:
            synapse_counts (list): List of integers (e.g., [2, 2, 3, 5, 10...])
            label (str): Name for the legend.
            color (str): Optional color for the line.
        """
        import matplotlib.pyplot as plt
        from collections import Counter

        if synapse_counts is None or len(synapse_counts) == 0:
            print(f"Warning: No data provided for label '{label}'. Skipping plot.")
            return

        freq_map = Counter(synapse_counts)

        sorted_x = sorted(freq_map.keys())
        y_values = [freq_map[x] for x in sorted_x]
        plt.plot(
            y_values, 
            sorted_x,
            marker=None, 
            linestyle='-', 
            linewidth=2, 
            markersize=1, 
            label=label, 
            alpha=0.2,
            color="blue"
        )
        plt.yscale('log')
        plt.xlabel('Number of Neurons')
        plt.ylabel('Number of Connections')
        plt.grid(True, linestyle=':', alpha=0.5)

    def get_top_partners_for_list(self, ct, root_ids, all_outputs, all_inputs):
        self.require_connection()
        i = 0
        for id in root_ids:
            outputs = all_outputs[all_outputs['pre_pt_root_id'] == id].copy()
            inputs = all_inputs[all_inputs['pre_pt_root_id'] == id].copy()

            partners = []
            if not outputs.empty:
                partners.extend(outputs["post_pt_root_id"].tolist())
            if not inputs.empty:
                partners.extend(inputs["pre_pt_root_id"].tolist())

            from collections import Counter
            counts = Counter(partners)
            top_list = counts.most_common()

            results = []
            for n in top_list:
                results.append(n)

            connection_counts = [item[1] for item in top_list if item[1] >= 2]
            self.add_connectivity_line(label='test', synapse_counts=connection_counts)
            i += 1
            print(f"Plotted neuron {id} connections ({i} in total)...")
        plt.savefig(f'saved_figures/{ct}.png', dpi=300, bbox_inches='tight')
        plt.cla()

    def graph_ct_connectivity (self, table_path):
        df = self.assign_cell_types(table_path)
        cell_types = df['cell_type'].unique()

        table_folder_name = os.path.basename(os.path.dirname(table_path))
        dir_path = r"C:\Users\ozolc\OneDrive\Dokumenty\Visual Studio Dir\Connectomics"

        for ct in cell_types:
            root_ids = df[df['cell_type'] == ct]['pt_root_id'].tolist()
            outputs_path = os.path.join(dir_path, 'saved_dataframes', table_folder_name, f'outputs_{ct}.parquet')
            inputs_path = os.path.join(dir_path, 'saved_dataframes', table_folder_name, f'inputs_{ct}.parquet')

            if not os.path.exists(outputs_path) or not os.path.exists(inputs_path):
                print(f"Skipping {ct}: Missing local data at {outputs_path}")
                continue
            all_outputs = pd.read_parquet(outputs_path)
            all_inputs = pd.read_parquet(inputs_path)
            self.get_top_partners_for_list(ct, root_ids, all_outputs, all_inputs)


# -------------------------------------------- NEUROGLANCER SETUP ----------------------------------------------
    def build_neuroglancer(self, client, root_ids, seg_source, img_source=None, resolution=None):
        self.require_connection()
        # seg_source and resolution parameters are optional and will be set to default for Minnie65 if left empty
        if resolution is None:
            resolution = [4, 4, 40]
        if resolution is not None:
            resolution = resolution
        
        viewer = statebuilder.ViewerState()
        # Set image source (raw EM data)
        def add_img_layer():
            if img_source is None:
                viewer.add_image_layer(
                    source=client.info.image_source(), 
                    name='em_imagery', 
                    resolution=resolution
                )
            if img_source is not None:
                viewer.add_image_layer(
                    source=img_source, 
                    name='em_imagery', 
                    resolution=resolution
                )

        # Set segmentation source
        def add_seg_layer():
            if seg_source == "static":
                static_source = "precomputed://gs://iarpa_microns/minnie/minnie65/seg_m1300"
                viewer.add_segmentation_layer(
                    source=static_source, 
                    name='live_segmentation',
                    resolution=resolution
                )
            if seg_source == "dynamic":
                dynamic_source = client.info.segmentation_source()
                viewer.add_segmentation_layer(
                    source=dynamic_source, 
                    name='live_segmentation',
                    resolution=resolution
                )

        add_img_layer()
        add_seg_layer()
        for id in root_ids:
            viewer.add_segments(
                segments=[id],
                visible=[True]
            )
            print(f"Added root id: {id} to Viewer.")

        link = viewer.to_url()
        print(link)
        return


# --------------------------------------------- HELPER FUNCTIONS ---------------------------------------------
    def require_connection(self):
        if self.client is None or self.cv is None:
            self.client, self.cv = self.initialize()
