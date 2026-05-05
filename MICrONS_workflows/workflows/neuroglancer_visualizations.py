import time
from caveclient import CAVEclient
from cloudvolume import CloudVolume
import neuroglancer
import threading
import pandas as pd
from nglui import statebuilder

class connections:
    def __init__(self):
        self.client = None
        self.cv = None
        self.lock = threading.RLock()
        self.mesh_source = None
        self.datastack_name = None
        self.root_ids = []
        self.viewer = None


# ------------------------------------------------- ACCESS -------------------------------------------------

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

# -------------------------------------------- NEUROGLANCER SETUP --------------------------------------------


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

    def get_scene_connections(self):
        self.require_connection()
        with self.lock:
            seg_ids = [int(m["seg_id"]) for m in self.root_ids.values() if m.get("status") == "done"]
        
        if len(seg_ids) < 2:
            return {"nodes": [], "links": []}

        synapses = self.client.materialize.synapse_query(
        pre_ids=seg_ids,
        post_ids=seg_ids
        )

        if synapses.empty:
            return {"nodes": [{"id": str(sid)} for sid in seg_ids], "links": []}

        links = []
        for (pre_id, post_id), group in synapses.groupby(["pre_pt_root_id", "post_pt_root_id"]):
            links.append({
                "pre": str(pre_id),
                "post": str(post_id),
                "weight": len(group),
                "coords": group["ctr_pt_position"].tolist() 
            })

        nodes = [{"id": str(sid), "name": f"Neuron_{sid}"} for sid in seg_ids]
        return {"nodes": nodes, "links": links}

    def get_multi_neuron_connections(self, root_id_list):
        self.require_connection()
        
        clean_ids = [int(rid) for rid in root_id_list]
        
        if not clean_ids:
            return {"nodes": [], "links": [], "mismatches": {}}
            
        with self.lock:
            print(f"Querying outputs for {len(clean_ids)} neurons...")
            outputs = self.client.materialize.synapse_query(pre_ids=clean_ids)
            
            print(f"Querying inputs for {len(clean_ids)} neurons...")
            inputs = self.client.materialize.synapse_query(post_ids=clean_ids)
            
        print("Merging synapses and extracting duplicates...")
        synapses = pd.concat([outputs, inputs], ignore_index=True)
        
        mismatches = {}
        
        if not synapses.empty:
            duplicate_mask = synapses.duplicated(subset=["id"], keep=False)
            duplicate_rows = synapses[duplicate_mask]
            for syn_id, group in duplicate_rows.groupby("id"):
                mismatches[str(syn_id)] = group.to_dict(orient="records")
            synapses = synapses.drop_duplicates(subset=["id"])
        if synapses.empty:
            nodes = [{"id": str(rid), "name": f"Target_{rid}"} for rid in clean_ids]
            return {"nodes": nodes, "links": [], "mismatches": mismatches}

        links = []
        for (pre_id, post_id), group in synapses.groupby(["pre_pt_root_id", "post_pt_root_id"]):
            links.append({
                "pre": str(pre_id),
                "post": str(post_id),
                "weight": len(group),
                "coords": group["ctr_pt_position"].tolist() 
            })

        unique_pre = synapses["pre_pt_root_id"].unique()
        unique_post = synapses["post_pt_root_id"].unique()
        all_involved_ids = set(unique_pre).union(set(unique_post)).union(set(clean_ids))
        
        nodes = [{"id": str(sid), "name": f"Neuron_{sid}"} for sid in all_involved_ids]
        
        print(f"Found {len(links)} unique connections. Extracted {len(mismatches)} overlapping synapses for mismatch checking.")
        
        return {
            "nodes": nodes, 
            "links": links, 
            "mismatches": mismatches
        }

    def create_synapse_annotations(self, links):
        annotations = []
        for link in links:
            pre_id = link['pre']
            post_id = link['post']
            coords = link['coords']
            for i, raw_coord in enumerate(coords):
                nm_coord = [
                    float(raw_coord[0] / 2),
                    float(raw_coord[1] / 2),
                    float(raw_coord[2])
                ]
                
                annotations.append(neuroglancer.PointAnnotation(
                    id=f"{pre_id}_{post_id}_{i}",
                    point=nm_coord
                ))
        return annotations

    def add_synapses_to_viewer(self, viewer, annotations, layer_name="synapses"):
        with viewer.txn() as s:
            s.layers.append(
                name=layer_name,
                layer=neuroglancer.AnnotationLayer(
                    annotations=annotations,
                    annotation_color='#ffff00' 
                )
            )
        return viewer


# -------------------------------------------- HELPER FUNCTIONS --------------------------------------------
    def require_connection(self):
        if self.client is None or self.cv is None:
            self.client, self.cv = self.initialize()
