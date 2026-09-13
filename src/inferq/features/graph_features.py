import logging
from typing import Any

from qiskit import QuantumCircuit

from inferq.features.graphs import IGGraphExtractor
from inferq.features.static_features import FeatureExtracter

# Configure logging
logger = logging.getLogger(__name__)

class GraphFeatureExtracter:
    """
    Orchestrator for extracting graph-based features from a circuit.

    Only Interaction Graph features are currently extracted; Gate Dependency
    Graph extraction is disabled.
    """
    def __init__(self, circuit: QuantumCircuit = None, feature_extractor: FeatureExtracter = None):
        self.feature_extractor = feature_extractor if feature_extractor else FeatureExtracter(circuit=circuit)
        self.extracted_features = self.feature_extractor.extracted_features
        self.circuit = circuit if circuit else self.feature_extractor.circuit
    
    def extractAllFeatures(self) -> dict[str, Any]:
        """
        Extracts the Interaction Graph features for the circuit.
        """
        logger.debug("Starting GraphFeatureExtracter...")
        
        # 1. Interaction Graph Features
        iggraph = IGGraphExtractor(circuit=self.circuit, feature_extractor=self.feature_extractor)
        ig_features = iggraph.extractAllFeatures()
        
        # 2. Gate Dependency Graph features are currently disabled; re-enabling
        # requires importing GDGGraphExtractor from inferq.features.graphs.
        # gdggraph = GDGGraphExtractor(circuit=self.circuit, feature_extractor=self.feature_extractor)
        # gdg_features = gdggraph.extractAllFeatures()

        # Update the local reference (though they should share the same dict via feature_extractor)
        self.extracted_features.update(ig_features)
        # self.extracted_features.update(gdg_features)
        
        return self.extracted_features



