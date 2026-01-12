from feature_extractors.graphs import IGGraphExtractor, GDGGraphExtractor
from typing import Any
from qiskit import QuantumCircuit
from feature_extractors.static_features import FeatureExtracter
import logging

# Configure logging
logger = logging.getLogger(__name__)

class GraphFeatureExtracter():
    """
    Orchestrator for extracting all graph-based features (Interaction Graph & Gate Dependency Graph).
    """
    def __init__(self, circuit: QuantumCircuit = None, feature_extractor: FeatureExtracter = None):
        self.feature_extractor = feature_extractor if feature_extractor else FeatureExtracter(circuit=circuit)
        self.extracted_features = self.feature_extractor.extracted_features
        self.circuit = circuit if circuit else self.feature_extractor.circuit
    
    def extractAllFeatures(self) -> dict[str, Any]:
        """
        Extracts features using both IGGraphExtractor and GDGGraphExtractor.
        """
        logger.debug("Starting GraphFeatureExtracter...")
        
        # 1. Interaction Graph Features
        iggraph = IGGraphExtractor(circuit=self.circuit, feature_extractor=self.feature_extractor)
        ig_features = iggraph.extractAllFeatures()
        
        # # 2. Gate Dependency Graph Features
        # gdggraph = GDGGraphExtractor(circuit=self.circuit, feature_extractor=self.feature_extractor)
        # gdg_features = gdggraph.extractAllFeatures()

        # Update the local reference (though they should share the same dict via feature_extractor)
        self.extracted_features.update(ig_features)
        # self.extracted_features.update(gdg_features)
        
        return self.extracted_features



