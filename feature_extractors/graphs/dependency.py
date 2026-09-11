from typing import Any
import sys
import logging
import rustworkx as rx
from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag, circuit_to_dagdependency
from qiskit.dagcircuit import DAGOpNode, DAGInNode
from feature_extractors.static_features import FeatureExtracter

# Configure logging
logger = logging.getLogger(__name__)

def convertToPyGraphGDG(circ: QuantumCircuit) -> rx.PyDiGraph:
    """
    Converts a Qiskit QuantumCircuit to a rustworkx PyGraph.
    This returns a gate dependency graph (GDG) where each gate is a node.
    Each edge represents a dependency between gates, with directed unweighted edges.
    Nodes correspond to gates, and edges represent dependencies.
    We will also add nodes for qubits.
    And their edges to the gates they are involved in immediately.
    Args:
        circ (QuantumCircuit): The quantum circuit to convert.
    Returns:
        rx.PyGraph: The constructed graph.
    """
    dag = circuit_to_dag(circ)
    gates = dag.gate_nodes()
    ge = dag.edges()

    # T=Each of these gates are DagOpNodes and are nodes of the graph
    # If DagInNode in in the edge, we know it came from a qubit
    # If DagOutNode is in the edge, we know it goes to output wire at the end
    # We will not add the edges to the DagOutNode
    # We will add the edges to the DagInNode (which connects qubits to gates)
    # Gates are also connected to each other
    n = circ.num_qubits
    gn = gates
    # let us make a map mapping the str version of the gate to the node integer index
    gate_to_index = {gn[i]: i + n for i in range(len(gn))}
    edges = []
    for e in ge:
        # if node not in map,m , we will add it
            
        
        if isinstance(e[0], DAGInNode) and isinstance(e[1], DAGOpNode):
            # e[0].wire is <Qubit register=(2, "q"), index=0>
            if e[1] not in gate_to_index:
                gate_to_index[e[1]] = len(gate_to_index) + n
            s = int(str(e[0].wire).split("index=")[1].split(")")[0].split(">")[0])
            edges.append((s, gate_to_index[e[1]], 1))
        elif isinstance(e[0], DAGOpNode) and isinstance(e[1], DAGOpNode):
            if e[0] not in gate_to_index:
                gate_to_index[e[0]] = len(gate_to_index) + n
            if e[1] not in gate_to_index:
                gate_to_index[e[1]] = len(gate_to_index) + n
            edges.append((gate_to_index[e[0]], gate_to_index[e[1]], 1))
    g = rx.PyDiGraph()
    g.add_nodes_from(range(len(gn) + n))
    # at the end go through the edges and add any nodes which are not in the graph
    for gate, index in gate_to_index.items():
        if index not in g.nodes():
            g.add_node(index)
    g.add_edges_from(edges)
    return g


class GDGGraphExtractor:
    def __init__(self, circuit: QuantumCircuit, feature_extractor: FeatureExtracter = None):
        """
        Initializes the GDGGraph with a QuantumCircuit.
        Converts the circuit to a rustworkx graph and precomputes shortest path distances.
        Args:
            circuit (QuantumCircuit): The quantum circuit to analyze.
        """
        self.rustxgraph = convertToPyGraphGDG(circuit)
        self.circuit = circuit
        self.feature_extractor = feature_extractor if feature_extractor else FeatureExtracter(circuit=circuit)
        self.extracted_features = self.feature_extractor.extracted_features
        self.dagdependecy = circuit_to_dagdependency(circuit) if circuit else None
    
    def getCriticalPathLength(self):
        """
        Returns the length of the critical path in the circuit.
        Returns:
            dict: {"critical_path_length": int}
        """
        if "critical_path_length" in self.extracted_features:
            return {"critical_path_length": self.extracted_features["critical_path_length"]}
        critical_path_length = rx.dag_longest_path_length(self.rustxgraph)
        self.extracted_features["critical_path_length"] = critical_path_length
        return {"critical_path_length": critical_path_length}
    
    def getPercentageOfGatesInCriticalPath(self):
        """
        Returns the percentage of gates that are part of the critical path.
        Returns:
            dict: {"percentage_of_gates_in_critical_path": float}
        """
        if "percentage_of_gates_in_critical_path" in self.extracted_features:
            return {"percentage_of_gates_in_critical_path": self.extracted_features["percentage_of_gates_in_critical_path"]}
        critical_path_length = self.getCriticalPathLength()["critical_path_length"]
        total_gates = self.circuit.size()
        percentage = (critical_path_length / total_gates) * 100 if total_gates > 0 else 0.0
        self.extracted_features["percentage_of_gates_in_critical_path"] = percentage
        return {"percentage_of_gates_in_critical_path": percentage}

    def extractAllFeatures(self) -> dict[str, Any]:
        """
        Extracts all features defined in GDGGraph and returns them as a single dictionary.
        If a feature method throws an error, None is put in the dict for that feature.
        Print messages are shown only if extract.py is the main file.
        Returns:
            dict: All extracted features.
        """
        
        is_main = sys.argv[0].endswith("extract.py")
        if is_main:
            logger.info("Starting GDGGraph feature extraction...")
        features = {}
        feature_methods = [
            ("critical_path_length", self.getCriticalPathLength),
            ("percentage_of_gates_in_critical_path", self.getPercentageOfGatesInCriticalPath),
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
            logger.info("Done extracting GDGGraph features.")
        return features
