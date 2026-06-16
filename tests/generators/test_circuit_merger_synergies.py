import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import os

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from config import get_synergy_rules
from generators.circuit_merger import CircuitMerger
from generators.lib.generator import BaseParams

class TestCircuitMergerSynergies(unittest.TestCase):
    
    def setUp(self):
        self.base_params = BaseParams(
            max_qubits=5, min_qubits=2, max_depth=10, min_depth=2, seed=42
        )
        
        # Create mocks with correct class names
        names = [
            "QFTGenerator", "QPE", "GHZ", "QuantumWalk", "QAOA", "VQEGenerator",
            "RealAmplitudes", "TwoLocal", "QNN", "WState", "GraphState", 
            "EfficientU2", "DeutschJozsa", "GroverNoAncilla"
        ]
        
        self.mock_generators = []
        for name in names:
            m = MagicMock()
            m.__class__.__name__ = name
            self.mock_generators.append(m)
            
        # Patch initialize_generators to return our mocks and avoid real init
        patcher = patch('generators.circuit_merger.CircuitMerger.initialize_generators', return_value=self.mock_generators)
        self.addCleanup(patcher.stop)
        self.mock_init = patcher.start()
        
        self.merger = CircuitMerger(self.base_params)

    def test_default_synergies_loaded(self):
        """Test that default synergies are loaded when no config provided"""
        self.assertEqual(self.merger.synergy_config, get_synergy_rules())

    def test_custom_synergies(self):
        """Test that custom synergies config is used if provided"""
        custom_config = [{"trigger": ["A"], "targets": ["B"], "multiplier": 10.0}]
        
        merger = CircuitMerger(self.base_params, synergy_config=custom_config)
        self.assertEqual(merger.synergy_config, custom_config)

    def test_apply_qft_synergy(self):
        """Test QFT -> QPE synergy (2.5x)"""
        names = [g.__class__.__name__ for g in self.mock_generators]
        names_arr = np.array(names)
        probs = np.ones(len(names))
        
        qpe_idx = names.index("QPE")
        
        self.merger._apply_specific_synergies(probs, "QFTGenerator", names_arr)
        
        self.assertAlmostEqual(probs[qpe_idx], 2.5)
        # Check unaffected
        self.assertAlmostEqual(probs[names.index("GHZ")], 1.0)

    def test_apply_ghz_synergy_stacking(self):
        """
        Test GHZ synergy stacking. 
        GHZ triggers:
        1. -> {QuantumWalk, QAOA, VQEGenerator} * 1.4
        2. -> {DeutschJozsa, GroverNoAncilla} * 1.3 (via Entangling group triggered by GHZ)
        """
        names = [g.__class__.__name__ for g in self.mock_generators]
        names_arr = np.array(names)
        probs = np.ones(len(names))
        
        qw_idx = names.index("QuantumWalk")
        dj_idx = names.index("DeutschJozsa")
        
        self.merger._apply_specific_synergies(probs, "GHZ", names_arr)
        
        # Rule 1 target
        self.assertAlmostEqual(probs[qw_idx], 1.4)
        # Rule 3 target
        self.assertAlmostEqual(probs[dj_idx], 1.3)

    def test_custom_config_logic(self):
        """Test logic with a completely custom configuration"""
        custom_config = [
            {"trigger": ["A"], "targets": ["B", "C"], "multiplier": 5.0},
            {"trigger": ["B"], "targets": ["C"], "multiplier": 2.0}
        ]
        
        # We need generators A, B, C, D in the merger's list or just pass appropriate names array
        # _apply_specific_synergies only needs names_arr
        
        merger = CircuitMerger(self.base_params, synergy_config=custom_config)
        
        names = ["A", "B", "C", "D"]
        names_arr = np.array(names)
        
        # Case 1: Trigger A
        probs = np.ones(4)
        merger._apply_specific_synergies(probs, "A", names_arr)
        # B and C should be *5
        self.assertEqual(probs[1], 5.0) # B
        self.assertEqual(probs[2], 5.0) # C
        self.assertEqual(probs[0], 1.0) # A
        self.assertEqual(probs[3], 1.0) # D

        # Case 2: Trigger B
        probs = np.ones(4)
        merger._apply_specific_synergies(probs, "B", names_arr)
        # C should be *2
        self.assertEqual(probs[2], 2.0) # C
        self.assertEqual(probs[0], 1.0) 
        self.assertEqual(probs[1], 1.0)

if __name__ == '__main__':
    unittest.main()
