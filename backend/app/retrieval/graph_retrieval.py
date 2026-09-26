"""
backend/app/retrieval/graph_retrieval.py
Graph retrieval and concept-neighbor expansion service.
Enables query expansion and relation-based paper retrieval for Node 4 / Step 6.5.
"""
import json
import logging
import os
import pickle
from typing import Dict, List, Optional, Tuple, Any

import networkx as nx
from networkx.readwrite import json_graph

logger = logging.getLogger("graph_retrieval")


class ConceptGraphRetriever:
    """Manages NetworkX concept graph traversal, neighbor expansion, and subgraph extraction."""

    def __init__(
        self,
        pickle_path: str = "data/processed/mesh_graph.gpickle",
        json_path: str = "data/processed/mesh_graph.json",
    ):
        self.pickle_path = pickle_path
        self.json_path = json_path
        self.graph: nx.Graph = nx.Graph()
        self._loaded = False
        self.load()

    def load(self) -> None:
        """Loads graph from pickle with JSON fallback."""
        if os.path.exists(self.pickle_path):
            try:
                with open(self.pickle_path, "rb") as f:
                    self.graph = pickle.load(f)
                self._loaded = True
                logger.info("Loaded graph from pickle: %d nodes, %d edges.", self.graph.number_of_nodes(), self.graph.number_of_edges())
                return
            except Exception as e:
                logger.warning("Failed to load graph pickle (%s); falling back to JSON.", e)

        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.graph = json_graph.node_link_graph(data)
                self._loaded = True
                logger.info("Loaded graph from JSON: %d nodes, %d edges.", self.graph.number_of_nodes(), self.graph.number_of_edges())
                return
            except Exception as e:
                logger.error("Failed to load graph from JSON (%s).", e)

        logger.warning("Graph file not found at %s or %s. Initialized with empty graph.", self.pickle_path, self.json_path)

    def get_mesh_terms_for_paper(self, pmid: str) -> List[str]:
        """Returns all MeSH base terms attached to a given paper."""
        node_id = f"paper:{pmid}"
        if not self.graph.has_node(node_id):
            return []
        terms = []
        for neighbor in self.graph.neighbors(node_id):
            if neighbor.startswith("mesh:"):
                terms.append(self.graph.nodes[neighbor].get("name", neighbor.replace("mesh:", "")))
        return terms

    def get_papers_for_mesh(self, mesh_term: str) -> List[str]:
        """Returns all PMIDs annotated with a specific MeSH descriptor."""
        node_id = f"mesh:{mesh_term}"
        if not self.graph.has_node(node_id):
            return []
        pmids = []
        for neighbor in self.graph.neighbors(node_id):
            if neighbor.startswith("paper:"):
                pmids.append(self.graph.nodes[neighbor].get("pmid", neighbor.replace("paper:", "")))
        return pmids

    def get_cooccurring_mesh_terms(self, mesh_term: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Finds concepts that most strongly co-occur with the given MeSH term."""
        node_id = f"mesh:{mesh_term}"
        if not self.graph.has_node(node_id):
            return []

        candidates = []
        for neighbor in self.graph.neighbors(node_id):
            if neighbor.startswith("mesh:"):
                edge_data = self.graph.get_edge_data(node_id, neighbor)
                weight = edge_data.get("weight", 1.0) if edge_data else 1.0
                name = self.graph.nodes[neighbor].get("name", neighbor.replace("mesh:", ""))
                candidates.append((name, weight))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]

    def expand_query_mesh_terms(self, query_mesh_terms: List[str], top_k: int = 5) -> List[str]:
        """Expands a list of query MeSH terms with high-confidence co-occurring concepts."""
        expanded = set(query_mesh_terms)
        for term in query_mesh_terms:
            neighbors = self.get_cooccurring_mesh_terms(term, top_k=top_k)
            for neighbor_term, _ in neighbors:
                expanded.add(neighbor_term)
        return sorted(list(expanded))

    def get_related_papers_by_mesh(self, pmid: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """
        Recommends related papers based on shared MeSH descriptors,
        scoring by Jaccard similarity across MeSH annotations.
        """
        source_mesh = set(self.get_mesh_terms_for_paper(pmid))
        if not source_mesh:
            return []

        candidate_scores: Dict[str, float] = {}
        for term in source_mesh:
            paper_pmids = self.get_papers_for_mesh(term)
            for other_pmid in paper_pmids:
                if str(other_pmid) == str(pmid):
                    continue
                if other_pmid not in candidate_scores:
                    other_mesh = set(self.get_mesh_terms_for_paper(other_pmid))
                    intersection = len(source_mesh & other_mesh)
                    union = len(source_mesh | other_mesh)
                    candidate_scores[other_pmid] = intersection / union if union > 0 else 0.0

        sorted_candidates = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_candidates[:top_k]

    def extract_subgraph_for_papers(self, pmids: List[str]) -> Dict[str, Any]:
        """
        Extracts an induced subgraph containing the specified papers and all their MeSH terms.
        Used for UI provenance and concept graph rendering in React drawers.
        """
        target_nodes = set()
        for pmid in pmids:
            paper_node = f"paper:{pmid}"
            if self.graph.has_node(paper_node):
                target_nodes.add(paper_node)
                for neighbor in self.graph.neighbors(paper_node):
                    if neighbor.startswith("mesh:"):
                        target_nodes.add(neighbor)

        sub_g = self.graph.subgraph(target_nodes)
        data = json_graph.node_link_data(sub_g)
        if "links" not in data and "edges" in data:
            data["links"] = data["edges"]
        elif "edges" not in data and "links" in data:
            data["edges"] = data["links"]
        return data
