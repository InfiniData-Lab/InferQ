import logging
from collections import Counter
from typing import Any

from qiskit import QuantumCircuit

# Configure logging
logger = logging.getLogger(__name__)



class FeatureExtracter:
    def __init__(self, circuit: QuantumCircuit = None):
        self.circuit = circuit
        self.extracted_features = {}


# ───────────────────────────────────────── static features

class StaticFeatureExtractor:

    def __init__(self, circuit: QuantumCircuit = None, feature_extractor: FeatureExtracter = None):
        """
        Initializes the StaticFeatureExtractor with a given QuantumCircuit.
        Args:
            circuit (QuantumCircuit, optional): The quantum circuit to analyze.
        """
        self.feature_extractor = feature_extractor if feature_extractor else FeatureExtracter(circuit=circuit)
        self.extracted_features = self.feature_extractor.extracted_features
        self.circuit = circuit if circuit else self.feature_extractor.circuit

    def getNumberOfQubits(self):
        """
        Returns the number of qubits in the circuit.
        Returns:
            dict: {"num_qubits": int}
        """
        if "num_qubits" in self.extracted_features:
            return {"num_qubits": self.extracted_features["num_qubits"]}
        value = self.circuit.num_qubits if self.circuit else 0
        self.extracted_features["num_qubits"] = value
        return {"num_qubits": value}

    def getGateCounts(self):
        """
        Returns a count of each gate type in the circuit.
        Returns:
            dict: {"gate_counts": {str: int}}
        """
        if "gate_counts" in self.extracted_features:
            return {"gate_counts": self.extracted_features["gate_counts"]}
        if not self.circuit:
            self.extracted_features["gate_counts"] = {}
            return {"gate_counts": {}}
        gate_counts = Counter(instruction.operation.name for instruction in self.circuit.data)
        self.extracted_features["gate_counts"] = dict(gate_counts)
        return {"gate_counts": dict(gate_counts)}

    def getWidth(self):
        """
        Returns the width of the circuit.
        Returns:
            dict: {"width": int}
        """
        if "width" in self.extracted_features:
            return {"width": self.extracted_features["width"]}
        value = self.circuit.width() if self.circuit else 0
        self.extracted_features["width"] = value
        return {"width": value}

    def getName(self):
        """
        Returns the name of the circuit.
        Returns:
            dict: {"name": str}
        """
        if "name" in self.extracted_features:
            return {"name": self.extracted_features["name"]}
        value = self.circuit.name if self.circuit else "Unnamed Circuit"
        self.extracted_features["name"] = value
        return {"name": value}

    def getTwoQubitGateCount(self):
        """
        Returns the number of two-qubit gates in the circuit.
        Returns:
            dict: {"two_qubit_gate_count": int}
        """
        if "two_qubit_gate_count" in self.extracted_features:
            return {"two_qubit_gate_count": self.extracted_features["two_qubit_gate_count"]}
        if not self.circuit:
            self.extracted_features["two_qubit_gate_count"] = 0
            return {"two_qubit_gate_count": 0}
        two_qubit_gates = [inst for inst in self.circuit.data if len(inst.qubits) == 2]
        value = len(two_qubit_gates)
        self.extracted_features["two_qubit_gate_count"] = value
        return {"two_qubit_gate_count": value}

    def getTwoQubitGatePercentage(self):
        """
        Returns the percentage of two-qubit gates in the circuit.
        Returns:
            dict: {"two_qubit_gate_percentage": float}
        """
        if "two_qubit_gate_percentage" in self.extracted_features:
            return {"two_qubit_gate_percentage": self.extracted_features["two_qubit_gate_percentage"]}
        two_qubit_gates = self.getTwoQubitGateCount()["two_qubit_gate_count"]
        total_gates = len(self.circuit.data) if self.circuit else 0
        percentage = (two_qubit_gates / total_gates) * 100 if total_gates > 0 else 0.0
        self.extracted_features["two_qubit_gate_percentage"] = percentage
        return {"two_qubit_gate_percentage": percentage}
    
    def getPauliGateCount(self):
        """
        Returns the count of Pauli gates (X, Y, Z) in the circuit.
        Returns:
            dict: {"pauli_gate_count": int}
        """
        if "pauli_gate_count" in self.extracted_features:
            return {"pauli_gate_count": self.extracted_features["pauli_gate_count"]}
        if not self.circuit:
            self.extracted_features["pauli_gate_count"] = 0
            return {"pauli_gate_count": 0}
        pauli_gates = [inst for inst in self.circuit.data if inst.operation.name in ['x', 'y', 'z']]
        value = len(pauli_gates)
        self.extracted_features["pauli_gate_count"] = value
        return {"pauli_gate_count": value}

    def getQiskitCircuitDepth(self):
        """
        Returns the depth of the circuit.
        Returns:
            dict: {"depth": int}
        """
        if "depth" in self.extracted_features:
            return {"depth": self.extracted_features["depth"]}
        value = self.circuit.depth() if self.circuit else 0
        self.extracted_features["depth"] = value
        return {"depth": value}
    
    def getDensityScore(self):
        """
        Bandic et al. method. 
        Calculated by (((2*number of two qubit gates + number of single qubit gates) / decomposed circuit depth) -1)/(number of qubits - 1)
        Returns:
            dict: {"density_score": float}
        """
        if "density_score" in self.extracted_features:
            return {"density_score": self.extracted_features["density_score"]}
        if not self.circuit:
            self.extracted_features["density_score"] = 0.0
            return {"density_score": 0.0}
        two_qubit_gates = self.getTwoQubitGateCount()["two_qubit_gate_count"]
        single_qubit_gates = len(self.getGateCounts()["gate_counts"])
        depth = self.getQiskitCircuitDepth()["depth"]
        num_qubits = self.getNumberOfQubits()["num_qubits"]
        if depth == 0 or num_qubits <= 1:
            self.extracted_features["density_score"] = 0.0
            return {"density_score": 0.0}
        density_score = (((2 * two_qubit_gates + single_qubit_gates) / depth) - 1) / (num_qubits - 1)
        self.extracted_features["density_score"] = density_score
        return {"density_score": density_score}

    def getIdlingScore(self):
        '''
        Calculates the idling score of the circuit. As written in Bandic et al.
        The idling score is defined as the average number of times a qubit is not used in the circuit.
        It is calculated as the sum of (depth - usage) for each qubit, divided
        by the product of the number of qubits and the depth of the circuit.
        Returns:
            dict: {"idling_score": float}
        '''
        if "idling_score" in self.extracted_features:
            return {"idling_score": self.extracted_features["idling_score"]}
        if not self.circuit:
            self.extracted_features["idling_score"] = 0.0
            return {"idling_score": 0.0}
        num_qubits = self.extracted_features["num_qubits"]
        depth = self.circuit.depth()
        if depth == 0 or num_qubits <= 1:
            self.extracted_features["idling_score"] = 0.0
            return {"idling_score": 0.0}
        qubit_usage = [0] * num_qubits
        
        for circuit_instruction in self.circuit.data:
            for q in circuit_instruction.qubits:
                s = int(str(q).split("index=")[1].split(")")[0].split(">")[0])
                qubit_usage[s] += 1

        if sum(qubit_usage) == 0:
            self.extracted_features["idling_score"] = 0.0
            return {"idling_score": 0.0}
        # Calculate idling score
        idling_score = sum((depth - usage) for usage in qubit_usage) / (num_qubits * depth)
        self.extracted_features["idling_score"] = idling_score
        return {"idling_score": idling_score}

    def getQuantumLocalityRatio(self):
        '''
        This measure the ratio between number of gates acting on local qubits vs long ditance ones. So if gates act on qubits that are close to each other, the locality ratio will be high.
        Returns:
            dict: {"locality_ratio": float}
        '''
        if "locality_ratio" in self.extracted_features:
            return {"locality_ratio": self.extracted_features["locality_ratio"]}
        if not self.circuit:
            self.extracted_features["locality_ratio"] = 0.0
            return {"locality_ratio": 0.0}
        num_qubits = self.circuit.num_qubits
        if num_qubits < 2:
            self.extracted_features["locality_ratio"] = 0.0
            return {"locality_ratio": 0.0}
        # for each gate, extracting the qubit indices
        # then check if they are all adjacent qubits. If not, then it is a long distance gate
        long_distance_gates = 0
        local_gates = 0
        for gate in self.circuit.data:
            qubits = [int(str(qubit).split("index=")[1].split(")")[0].split(">")[0]) for qubit in gate.qubits]
            if len(qubits) < 2:
                local_gates += 1
                continue
            if all(abs(qubits[i] - qubits[i + 1]) == 1 for i in range(len(qubits) - 1)):
                local_gates += 1
            else:
                long_distance_gates += 1
        locality_ratio = local_gates / (local_gates + long_distance_gates) if (local_gates + long_distance_gates) > 0 else 0.0
        self.extracted_features["locality_ratio"] = locality_ratio
        return {"locality_ratio": locality_ratio}
    
        

    def extractAllFeatures(self) -> dict[str, Any]:
        """
        Extracts all basic features from the quantum circuit.
        If a feature method throws an error, None is put in the dict for that feature.
        Print messages are shown only if extract.py is the main file.
        Returns:
            dict: All extracted features.
        """
        import sys
        
        is_main = sys.argv[0].endswith("extract.py")
        if is_main:
            logger.info("Starting Static feature extraction...")
        features = {}
        feature_methods = [
            ("num_qubits", self.getNumberOfQubits),
            ("gate_counts", self.getGateCounts),
            ("width", self.getWidth),
            ("name", self.getName),
            ("pauli_gate_count", self.getPauliGateCount),
            ("two_qubit_gate_count", self.getTwoQubitGateCount),
            ("two_qubit_gate_percentage", self.getTwoQubitGatePercentage),
            ("depth", self.getQiskitCircuitDepth),
            ("density_score", self.getDensityScore),
            ("idling_score", self.getIdlingScore),
            ("locality_ratio", self.getQuantumLocalityRatio),
        ]
        is_main = sys.argv[0].endswith("extract.py")
        for key, method in feature_methods:
            try:
                result = method()
                # result is a dict with one key
                value = list(result.values())[0] if isinstance(result, dict) and result else None
                features[key] = value
                if is_main:
                    logger.debug(f"{key} feature completed.")
            except Exception as e:
                features[key] = None
                if is_main:
                    logger.warning(f"{key} feature failed: {e}")
        if is_main:
            logger.info("Done extracting Static features.")
        return features