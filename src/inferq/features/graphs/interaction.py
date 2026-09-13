import logging
import sys
from typing import Any

import numpy as np
import rustworkx as rx
from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag

from inferq.features.static_features import FeatureExtracter

# Configure logging
logger = logging.getLogger(__name__)

def convertToPyGraphIG(circ: QuantumCircuit) -> rx.PyGraph:
    """
    Converts a Qiskit QuantumCircuit to a rustworkx PyGraph.
    Each two-qubit gate is represented as an edge, with edge weights counting occurrences.
    Nodes correspond to qubits.
    Returns:
        rx.PyGraph: The constructed graph.
    """
    dag = circuit_to_dag(circ)
    # not only 2 qubit ops, but all gates, we need add interaction between qubits. e.g otffoli (ccx) gate acting
    # on 3 qubits, we will add edges between all 3 qubits 0, 1, 2
    # so we will add edges between (0,1), (0,2), (1,2) and so on
    # we will add edges between all qubits that are involved in the gate
    alledges = []
    for gate in dag.gate_nodes():
        qubits = [int(str(qubit).split("index=")[1].split(")")[0].split(">")[0]) for qubit in gate.qargs]
        if len(qubits) < 2:
            continue
        for i in range(len(qubits)):
            for j in range(i + 1, len(qubits)):
                alledges.append((qubits[i], qubits[j]))
    edges = {}
    for edge in alledges:
        if edge in edges.keys():
            edges[edge] += 1
        else:
            edges[edge] = 1
    g = rx.PyGraph()
    g.add_nodes_from(range(circ.num_qubits))
    g.add_edges_from([(q, q2, v) for (q, q2), v in edges.items()])
    return g


class IGGraphExtractor:

    def __init__(self, circuit : QuantumCircuit, feature_extractor: FeatureExtracter = None):
        """
        Initializes the IGGraph with a QuantumCircuit.
        Converts the circuit to a rustworkx graph and precomputes shortest path distances.
        Args:
            circuit (QuantumCircuit): The quantum circuit to analyze.
        """
        self.circuit = circuit
        self.rustxgraph = convertToPyGraphIG(circuit)
        self.distances = rx.floyd_warshall(self.rustxgraph, weight_fn=float)
        self.rustxdigraph = self.rustxgraph.to_directed()
        self.feature_extractor = feature_extractor if feature_extractor else FeatureExtracter(circuit=circuit)
        self.extracted_features = self.feature_extractor.extracted_features

    def getIGDepth(self):
        """
        Returns the depth of the circuit.
        Returns:
            dict: {"igdepth": int}
        """
        if "igdepth" in self.extracted_features:
            return {"igdepth": self.extracted_features["igdepth"]}
        value = self.circuit.depth() if self.circuit else 0
        self.extracted_features["igdepth"] = value
        return {"igdepth": value}

    def getRadius(self):
        """
        Returns the radius of the graph (minimum eccentricity).
        Returns:
            dict: {"radius": float}
        """
        if "radius" in self.extracted_features:
            return {"radius": self.extracted_features["radius"]}
        radius = min(
            max(self.distances[node].values()) for node in self.distances if self.distances[node]
        )
        self.extracted_features["radius"] = radius
        return {"radius": radius}
    
    def getDiameter(self):
        """
        Returns the diameter of the graph (maximum shortest path length).
        Returns:
            dict: {"diameter": float}
        """
        if "diameter" in self.extracted_features:
            return {"diameter": self.extracted_features["diameter"]}
        diameter = max(
            dist
            for row in self.distances.values()
            for dist in row.values()
            if dist is not None
        )
        self.extracted_features["diameter"] = diameter
        return {"diameter": diameter}
    
    def getConnectedComponents(self):
        """
        Returns the connected components of the graph.
        Returns:
            dict: {"connected_components": list[list[int]]}
        """
        if "connected_components" in self.extracted_features:
            return {"connected_components": self.extracted_features["connected_components"]}
        components = rx.connected_components(self.rustxgraph)
        result = [list(comp) for comp in components]
        self.extracted_features["connected_components"] = result
        return {"connected_components": result}

    def getMaxDegree(self):
        """
        Returns the maximum degree of any node in the graph.
        Returns:
            dict: {"max_degree": int}
        """
        if "max_degree" in self.extracted_features:
            return {"max_degree": self.extracted_features["max_degree"]}
        degrees = [self.rustxgraph.degree(node) for node in range(self.circuit.num_qubits)]
        max_deg = max(degrees) if degrees else 0
        self.extracted_features["max_degree"] = int(max_deg)
        return {"max_degree": int(max_deg)}

    def getMinCut(self):
        """
        Returns the upper bound of the minimum cut of the graph.
        Returns:
            dict: {"min_cut_upper": int}
        """
        if "min_cut_upper" in self.extracted_features:
            return {"min_cut_upper": self.extracted_features["min_cut_upper"]}
        min_cut = rx.stoer_wagner_min_cut(self.rustxgraph)[0] if self.rustxgraph.num_edges() else 0
        self.extracted_features["min_cut_upper"] = int(min_cut)
        return {"min_cut_upper": int(min_cut)}

    def getEdgeCount(self):
        """
        Returns the number of edges in the graph.
        Returns:
            dict: {"edge_count": int}
        """
        if "edge_count" in self.extracted_features:
            return {"edge_count": self.extracted_features["edge_count"]}
        edge_count = self.rustxgraph.num_edges() if self.rustxgraph else 0
        self.extracted_features["edge_count"] = int(edge_count)
        return {"edge_count": int(edge_count)}

    def getNodeCount(self):
        """
        Returns the number of nodes in the graph.
        Returns:
            dict: {"node_count": int}
        """
        if "node_count" in self.extracted_features:
            return {"node_count": self.extracted_features["node_count"]}
        node_count = self.rustxgraph.num_nodes() if self.rustxgraph else 0
        self.extracted_features["node_count"] = int(node_count)
        return {"node_count": int(node_count)}
    
    def getAverageDegree(self):
        """
        Returns the average degree of nodes in the graph.
        Returns:
            dict: {"average_degree": float}
        """
        if "average_degree" in self.extracted_features:
            return {"average_degree": self.extracted_features["average_degree"]}
        if self.rustxgraph.num_nodes() == 0:
            self.extracted_features["average_degree"] = 0.0
            return {"average_degree": 0.0}
        total_degree = sum(self.rustxgraph.degree(node) for node in range(self.rustxgraph.num_nodes()))
        average_degree = total_degree / self.rustxgraph.num_nodes()
        self.extracted_features["average_degree"] = average_degree
        return {"average_degree": average_degree}
    
    def getStandardDeviationAdjacencyMatrix(self):
        """
        Returns the standard deviation of the adjacency matrix values.
        Returns:
            dict: {"std_dev_adjacency_matrix": float}
        """
        if "std_dev_adjacency_matrix" in self.extracted_features:
            return {"std_dev_adjacency_matrix": self.extracted_features["std_dev_adjacency_matrix"]}
        if self.rustxgraph.num_nodes() == 0:
            self.extracted_features["std_dev_adjacency_matrix"] = 0.0
            return {"std_dev_adjacency_matrix": 0.0}
        adjacency_matrix = rx.adjacency_matrix(self.rustxgraph, weight_fn=float)
        std_dev = np.std(adjacency_matrix)
        self.extracted_features["std_dev_adjacency_matrix"] = std_dev
        return {"std_dev_adjacency_matrix": std_dev}

    def getCentralPointOfDominence(self):
        """
        Returns the maximum betweenness centrality value in the graph.
        Returns:
            dict: {"central_point_of_dominance": float}
        """
        if "central_point_of_dominance" in self.extracted_features:
            return {"central_point_of_dominance": self.extracted_features["central_point_of_dominance"]}
        if self.rustxgraph.num_nodes() == 0:
            self.extracted_features["central_point_of_dominance"] = 0.0
            return {"central_point_of_dominance": 0.0}
        centrality = rx.betweenness_centrality(self.rustxgraph, normalized=True)
        max_centrality = max(centrality.values())
        self.extracted_features["central_point_of_dominance"] = max_centrality
        return {"central_point_of_dominance": max_centrality}
    
    def getCoreNumber(self):
        """
        Returns the core number for each node in the graph.
        Returns:
            dict: {"core_number": dict}
        """
        if "core_number" in self.extracted_features:
            return {"core_number": self.extracted_features["core_number"]}
        if self.rustxgraph.num_nodes() == 0:
            self.extracted_features["core_number"] = {}
            return {"core_number": {}}
        core_numbers = rx.core_number(self.rustxgraph)
        result = dict(enumerate(core_numbers))
        self.extracted_features["core_number"] = result
        return {"core_number": result}

    def getAverageClusteringCoefficient(self):
        """
        Returns the average clustering coefficient (transitivity) of the graph.
        Returns:
            dict: {"average_clustering_coefficient": float}
        """
        if "average_clustering_coefficient" in self.extracted_features:
            return {"average_clustering_coefficient": self.extracted_features["average_clustering_coefficient"]}
        if self.rustxgraph.num_nodes() == 0:
            self.extracted_features["average_clustering_coefficient"] = 0.0
            return {"average_clustering_coefficient": 0.0} 
        coeff = rx.transitivity(self.rustxgraph)
        self.extracted_features["average_clustering_coefficient"] = coeff
        return {"average_clustering_coefficient": coeff}
    
    def getAverageShortestPathLength(self):
        """
        Returns the average shortest path length between all pairs of nodes.
        Returns:
            dict: {"average_shortest_path_length": float}
        """
        if "average_shortest_path_length" in self.extracted_features:
            return {"average_shortest_path_length": self.extracted_features["average_shortest_path_length"]}
        if self.rustxgraph.num_nodes() == 0:    
            self.extracted_features["average_shortest_path_length"] = 0.0
            return {"average_shortest_path_length": 0.0}
        total_length = 0
        count = 0
        for node, dist_dict in self.distances.items():
            for target, length in dist_dict.items():
                if length is not None and node != target:
                    total_length += length
                    count += 1
        average_length = total_length / count if count > 0 else 0.0
        self.extracted_features["average_shortest_path_length"] = average_length
        return {"average_shortest_path_length": average_length}
    
    def getPageRank(self):
        """
        Returns the PageRank values for each node in the graph.
        Returns:
            dict: {"pagerank": dict}
        """
        # This method calculates the PageRank of the graph.
        # using the digraph version of the graph self.rustxdigraph
        if "pagerank" in self.extracted_features:
            return {"pagerank": self.extracted_features["pagerank"]}
        if self.rustxdigraph.num_nodes() == 0:
            self.extracted_features["pagerank"] = {}
            return {"pagerank": {}}
        pagerank_values = rx.pagerank(self.rustxdigraph, alpha=0.85)
        result = dict(enumerate(pagerank_values))
        self.extracted_features["pagerank"] = result
        return {"pagerank": result}
    
    def extractAllFeatures(self) -> dict[str, Any]:
        """
        Extracts all features defined in IGGraph and returns them as a single dictionary.
        If a feature method throws an error, None is put in the dict for that feature.
        Print messages are shown only if extract.py is the main file.
        Returns:
            dict: All extracted features.
        """
        
        is_main = sys.argv[0].endswith("extract.py")
        if is_main:
            logger.info("Starting IGGraph feature extraction...")
        features = {}
        feature_methods = [
            ("igdepth", self.getIGDepth),
            ("diameter", self.getDiameter),
            ("radius", self.getRadius),
            ("connected_components", self.getConnectedComponents),
            ("max_degree", self.getMaxDegree),
            ("min_cut_upper", self.getMinCut),
            ("edge_count", self.getEdgeCount),
            ("node_count", self.getNodeCount),
            ("average_degree", self.getAverageDegree),
            ("std_dev_adjacency_matrix", self.getStandardDeviationAdjacencyMatrix),
            ("central_point_of_dominance", self.getCentralPointOfDominence),
            ("core_number", self.getCoreNumber),
            ("average_clustering_coefficient", self.getAverageClusteringCoefficient),
            ("average_shortest_path_length", self.getAverageShortestPathLength),
            ("pagerank", self.getPageRank),
        ]
        for key, method in feature_methods:
            try:
                result = method()
                value = list(result.values())[0] if isinstance(result, dict) and result else None
                features[key] = value
                if is_main:
                    logger.debug(f"{key} feature completed.")
            except Exception as e:
                features[key] = None
                if is_main:
                    logger.warning(f"{key} feature failed: {e}")
        if is_main:
            logger.info("Done extracting IGGraph features.")
        return features
