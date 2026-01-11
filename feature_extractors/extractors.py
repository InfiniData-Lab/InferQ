from feature_extractors.graph_features import GraphFeatureExtracter
from feature_extractors.static_features import StaticFeatureExtractor
from feature_extractors.dynamic_features import DynamicFeatureExtractor
from feature_extractors.static_features import FeatureExtracter
from feature_extractors.graphs import IGGraphExtractor, GDGGraphExtractor
from qiskit import QuantumCircuit
import logging

# Configure logging
logger = logging.getLogger(__name__)

def extract_features(circuit: QuantumCircuit):
    """
    Extracts static and graph features from a given quantum circuit.
    
    Args:
        circuit (QuantumCircuit): The quantum circuit to analyze.
    
    Returns:
        dict: A dictionary containing extracted features.
    """
    logger.info(f"Starting feature extraction for circuit: {circuit.num_qubits} qubits, depth {circuit.depth()}")
    
    if not isinstance(circuit, QuantumCircuit):
        raise ValueError("Input must be a QuantumCircuit instance.")
    
    try:
        # Initialize feature extractors
        logger.debug("Initializing feature extractors...")
        feature_extractor = FeatureExtracter(circuit=circuit)
        
        # Main extractors
        static_feature_extractor = StaticFeatureExtractor(circuit=circuit, feature_extractor=feature_extractor)
        graph_feature_extractor = GraphFeatureExtracter(circuit=circuit, feature_extractor=feature_extractor)
        dynamic_feature_extractor = DynamicFeatureExtractor(circuit=circuit, feature_extractor=feature_extractor)
        
        logger.debug("✓ Feature extractors initialized")
        
        # Extract features
        logger.debug("Extracting static features...")
        features = static_feature_extractor.extractAllFeatures()
        logger.debug(f"✓ Static features extracted: {len(features)} features")
        
        logger.debug("Extracting graph features (IG + GDG)...")
        graph_features = graph_feature_extractor.extractAllFeatures()
        features.update(graph_features)
        logger.debug(f"✓ Graph features extracted: {len(graph_features)} features")
        
        logger.debug("Extracting dynamic features...")
        dynamic_features = dynamic_feature_extractor.extractAllFeatures()
        features.update(dynamic_features)
        logger.debug(f"✓ Dynamic features extracted: {len(dynamic_features)} features")
        
        logger.info(f"✓ Feature extraction completed: {len(features)} total features")
        return features
        
    except Exception as e:
        logger.error(f"Feature extraction failed: {e}")
        raise