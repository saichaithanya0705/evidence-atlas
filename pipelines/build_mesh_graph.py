"""
pipelines/build_mesh_graph.py
Constructs bipartite Paper-MeSH graph and MeSH co-occurrence relations using NetworkX 3.6.
Implements FEAT-R2-08.
"""
import argparse
import json
import logging
import os
import pickle
from collections import defaultdict
from typing import Dict, List, Any

import networkx as nx
from networkx.readwrite import json_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_mesh_graph")


def build_concept_graph(
    clean_jsonl_or_parquet: str,
    output_gpickle_path: str,
    output_json_path: str,
    manifest_path: str,
) -> nx.Graph:
    """
    Constructs a NetworkX graph linking papers and MeSH concepts.
    Serializes to pickle and JSON node-link format with full NetworkX 3.6 compatibility.
    """
    logger.info("Building concept graph from: %s", clean_jsonl_or_parquet)

    records = []
    if clean_jsonl_or_parquet.endswith(".jsonl"):
        with open(clean_jsonl_or_parquet, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
    else:
        import pandas as pd
        df = pd.read_parquet(clean_jsonl_or_parquet)
        records = df.to_dict(orient="records")

    logger.info("Loaded %d records for graph construction.", len(records))

    G = nx.Graph()
    mesh_paper_counts = defaultdict(int)
    mesh_cooccurrence = defaultdict(int)

    # 1. Add paper and MeSH nodes, plus paper-mesh edges
    for rec in records:
        pmid = str(rec["pmid"])
        paper_node_id = f"paper:{pmid}"

        G.add_node(
            paper_node_id,
            node_type="paper",
            pmid=pmid,
            title=rec.get("title", ""),
            year=rec.get("year"),
            study_type=rec.get("study_type", "Other"),
        )

        terms = rec.get("mesh_terms", [])
        for term in terms:
            if not term:
                continue
            mesh_node_id = f"mesh:{term}"
            mesh_paper_counts[term] += 1

            if not G.has_node(mesh_node_id):
                G.add_node(
                    mesh_node_id,
                    node_type="mesh",
                    name=term,
                    frequency=0,
                )

            # Add bipartite edge
            G.add_edge(paper_node_id, mesh_node_id, relation="annotated_with", weight=1.0)

        # Pairwise co-occurrences for MeSH-MeSH links
        unique_terms = sorted(list(set(t for t in terms if t)))
        for i in range(len(unique_terms)):
            for j in range(i + 1, len(unique_terms)):
                pair = (unique_terms[i], unique_terms[j])
                mesh_cooccurrence[pair] += 1

    # Update frequencies on MeSH nodes
    for term, freq in mesh_paper_counts.items():
        node_id = f"mesh:{term}"
        if G.has_node(node_id):
            G.nodes[node_id]["frequency"] = freq

    # 2. Add MeSH-MeSH co-occurrence edges
    cooccur_edges_count = 0
    for (m1, m2), weight in mesh_cooccurrence.items():
        n1 = f"mesh:{m1}"
        n2 = f"mesh:{m2}"
        if G.has_node(n1) and G.has_node(n2):
            G.add_edge(n1, n2, relation="co_occurs_with", weight=float(weight))
            cooccur_edges_count += 1

    paper_count = sum(1 for _, data in G.nodes(data=True) if data.get("node_type") == "paper")
    mesh_count = sum(1 for _, data in G.nodes(data=True) if data.get("node_type") == "mesh")
    total_edges = G.number_of_edges()

    logger.info("Graph construction complete: %d papers, %d MeSH terms, %d edges (%d co-occurrence edges).",
                paper_count, mesh_count, total_edges, cooccur_edges_count)

    # 3. Serialization (NetworkX 3.6 safe pickle)
    os.makedirs(os.path.dirname(output_gpickle_path), exist_ok=True)
    with open(output_gpickle_path, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Saved binary graph pickle to: %s", output_gpickle_path)

    # 4. JSON node-link export for portability & UI inspection
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    json_data = json_graph.node_link_data(G)
    if "links" not in json_data and "edges" in json_data:
        json_data["links"] = json_data["edges"]
    elif "edges" not in json_data and "links" in json_data:
        json_data["edges"] = json_data["links"]
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False)
    logger.info("Saved portable JSON graph to: %s", output_json_path)

    # 5. Manifest
    manifest_data = {
        "total_nodes": G.number_of_nodes(),
        "paper_nodes": paper_count,
        "mesh_nodes": mesh_count,
        "total_edges": total_edges,
        "mesh_cooccurrence_edges": cooccur_edges_count,
        "density": nx.density(G) if G.number_of_nodes() > 0 else 0.0,
        "pickle_path": output_gpickle_path,
        "json_path": output_json_path,
    }
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    return G


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build NetworkX Paper-MeSH concept graph.")
    parser.add_argument("--input", default="data/processed/cleaned_pubmed.jsonl")
    parser.add_argument("--output-pickle", default="data/processed/mesh_graph.gpickle")
    parser.add_argument("--output-json", default="data/processed/mesh_graph.json")
    parser.add_argument("--manifest", default="data/manifests/graph_manifest.json")
    args = parser.parse_args()

    build_concept_graph(args.input, args.output_pickle, args.output_json, args.manifest)
