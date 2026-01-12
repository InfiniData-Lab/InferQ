#!/usr/bin/env python3
"""
Pipeline Worker Module

Handles individual circuit processing tasks in parallel workers.
Each worker processes a single circuit through the complete pipeline:
1. Circuit generation
2. Duplicate detection  
3. Feature extraction
4. Simulation
5. Local storage
"""

import logging
import sys
import signal
from datetime import datetime
from pathlib import Path
from typing import Set

from generators.circuit_merger import CircuitMerger
from generators.lib.generator import BaseParams
from config import get_circuit_config, get_simulation_config, get_storage_config
from utils.save_utils import save_circuit_locally
from feature_extractors.extractors import extract_features
from simulators.simulate import QuantumSimulator
from simulators import process_simulation_data_for_features
from utils.duplicate_detector import is_circuit_duplicate, initialize_duplicate_detection

def setup_worker_signal_handling():
    """Set up signal handling for worker processes."""
    def worker_signal_handler(signum, frame):
        # Worker processes should exit quickly on interrupt
        sys.exit(1)
    
    signal.signal(signal.SIGINT, worker_signal_handler)
    signal.signal(signal.SIGTERM, worker_signal_handler)

def run_single_pipeline(worker_id: int, seed_offset: int, existing_session_hashes: Set[str] = None) -> dict:
    """
    Run a single pipeline iteration optimized for performance.
    
    Args:
        worker_id: Worker process ID
        seed_offset: Seed offset for randomization
        
    Returns:
        Dictionary with pipeline results including circuit data for remote upload
    """
    try:
        # Configure worker-specific logging
        worker_logger = _setup_worker_logging(worker_id)
        worker_logger.info(f"Starting pipeline iteration (seed_offset={seed_offset})")
        
        # Get circuit, simulation, and storage configuration from centralized config
        circuit_config = get_circuit_config()
        simulation_config = get_simulation_config()
        storage_config = get_storage_config()
        seed=circuit_config['seed'] + seed_offset + worker_id * 1000
        # Initialize components using centralized configuration
        base_params = BaseParams(
            max_qubits=circuit_config['max_qubits'], 
            min_qubits=circuit_config['min_qubits'], 
            max_depth=circuit_config['max_depth'], 
            min_depth=circuit_config['min_depth'], 
            seed=seed, 
            measure=circuit_config['measure']
        )
        # Calculate simulation seed
        sim_seed = simulation_config['seed'] + seed_offset + worker_id * 1000
        worker_logger.debug(f"Initializing components with circuit seed {seed}, simulation seed {sim_seed}")
        circuit_merger = CircuitMerger(base_params=base_params)
        quantum_simulator = QuantumSimulator(
            seed=sim_seed,
            shots=simulation_config['shots'],
            timeout_seconds=simulation_config['timeout_seconds']
        )
        
        # Step 1: Generate circuit
        worker_logger.debug("Step 1: Generating circuit...")
        circuit = circuit_merger.generate_hierarchical_circuit(
            stopping_probability=circuit_config['stopping_probability'],
            max_generators=circuit_config['max_generators']
        )
        worker_logger.info(f"Generated circuit: {circuit.num_qubits} qubits, depth {circuit.depth()}, size {circuit.size()}")
        if(circuit.size()>circuit_config["max_circuit_size"]):
            return _create_error_result(worker_id, Exception("Circuit too complex..."))
        # Step 2: Check for duplicates BEFORE expensive operations
        worker_logger.debug("Step 2: Checking for duplicates...")
        
        # Initialize duplicate detection in worker process (loads from cache)
        initialize_duplicate_detection()
        
        # Add existing session hashes from other workers
        if existing_session_hashes:
            from utils.duplicate_detector import get_duplicate_detector
            detector = get_duplicate_detector()
            detector.add_session_hashes(existing_session_hashes)
            worker_logger.debug(f"Worker loaded {len(existing_session_hashes)} existing session hashes")
        
        is_duplicate, circuit_hash = is_circuit_duplicate(circuit)
        
        if is_duplicate:
            worker_logger.info(f"🔍 DUPLICATE DETECTED: Circuit {circuit_hash[:8]}... already exists - skipping expensive operations")
            return _create_duplicate_result(worker_id, circuit, circuit_hash)
        
        worker_logger.info(f"🆕 NEW CIRCUIT: {circuit_hash[:8]}... - proceeding with full processing")
        
        # Step 3: Extract features (only for new circuits)
        worker_logger.debug("Step 3: Extracting features...")
        features = extract_features(circuit=circuit)
        worker_logger.debug(f"Extracted {len(features)} features")
        
        # Step 4: Run simulations (only for new circuits)
        worker_logger.debug("Step 4: Running simulations...")
        simulation_results = quantum_simulator.simulate_all_methods(circuit)
        successful_sims = sum(1 for r in simulation_results.values() if r.get('success', False))
        worker_logger.info(f"Simulations completed: {successful_sims}/{len(simulation_results)} successful")
        
        # Step 5: Process simulation data
        worker_logger.debug("Step 5: Processing simulation data...")
        combined_features = process_simulation_data_for_features(simulation_results, features)
        
        # Step 6: Save locally (we know it's new, so should save successfully)
        worker_logger.debug("Step 6: Saving circuit locally...")
        storage_path = Path(storage_config['local_circuits_dir'])
        storage_path.mkdir(parents=True, exist_ok=True)
        
        saved_hash, saved_features, written = save_circuit_locally(
            circuit, combined_features, storage_path, expected_hash=circuit_hash
        )
        worker_logger.info(f"Circuit saved: hash={saved_hash[:8]}..., written={written}")
        
        # Use the original circuit_hash (computed once) for consistency
        return _create_success_result(worker_id, circuit, circuit_hash, 
                                    combined_features, saved_features, written)
        
    except Exception as e:
        return _create_error_result(worker_id, e)

def _setup_worker_logging(worker_id: int) -> logging.Logger:
    """
    Set up worker-specific logging.
    
    Args:
        worker_id: Worker process ID
        
    Returns:
        Configured logger for the worker
    """
    # Create worker-specific logger
    worker_logger = logging.getLogger(f'worker_{worker_id}')
    worker_logger.setLevel(logging.INFO)
    
    # Create formatter that includes worker ID
    formatter = logging.Formatter(f'%(asctime)s - WORKER-{worker_id} - %(levelname)s - %(message)s')
    
    # Add handler if not already present
    if not worker_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        worker_logger.addHandler(handler)
        worker_logger.propagate = False  # Prevent duplicate messages
    
    return worker_logger

def _create_duplicate_result(worker_id: int, circuit, circuit_hash: str) -> dict:
    """Create result dictionary for duplicate circuits."""
    # Get worker's session hashes for batch coordination
    from utils.duplicate_detector import get_duplicate_detector
    detector = get_duplicate_detector()
    worker_session_hashes = detector.get_session_hashes()
    
    return {
        'success': True,
        'worker_id': worker_id,
        'circuit_hash': circuit_hash,
        'circuit_qubits': circuit.num_qubits,
        'circuit_depth': circuit.depth(),
        'circuit_size': circuit.size(),
        'features_count': 0,
        'written': False,  # Not written because it's a duplicate
        'duplicate': True,
        'timestamp': datetime.now().isoformat(),
        # No circuit data for upload since it's a duplicate
        'circuit': None,
        'features': {},
        'serialization_method': None,
        # Include session hashes for batch coordination
        'worker_session_hashes': worker_session_hashes
    }

def _create_success_result(worker_id: int, circuit, circuit_hash: str,
                          combined_features: dict, saved_features: dict, written: bool) -> dict:
    """Create result dictionary for successful processing."""
    # Get worker's session hashes for batch coordination
    from utils.duplicate_detector import get_duplicate_detector
    detector = get_duplicate_detector()
    worker_session_hashes = detector.get_session_hashes()
    
    return {
        'success': True,
        'worker_id': worker_id,
        'circuit_hash': circuit_hash,  # Use the original hash computed once
        'circuit_qubits': circuit.num_qubits,
        'circuit_depth': circuit.depth(),
        'circuit_size': circuit.size(),
        'features_count': len(combined_features),
        'written': written,
        'duplicate': False,
        'timestamp': datetime.now().isoformat(),
        # Include data for remote upload
        'circuit': circuit,
        'features': saved_features,
        'serialization_method': saved_features.get('serialization_method', 'qpy'),
        # Include session hashes for batch coordination
        'worker_session_hashes': worker_session_hashes
    }

def _create_error_result(worker_id: int, error: Exception) -> dict:
    """Create result dictionary for failed processing."""
    # Use worker logger if available, otherwise fall back to regular logging
    try:
        worker_logger = logging.getLogger(f'worker_{worker_id}')
        worker_logger.error(f"Pipeline failed: {str(error)}")
    except:
        logger = logging.getLogger(__name__)
        logger.error(f"Worker {worker_id} pipeline failed: {str(error)}")
    
    return {
        'success': False,
        'worker_id': worker_id,
        'error': str(error),
        'timestamp': datetime.now().isoformat()
    }