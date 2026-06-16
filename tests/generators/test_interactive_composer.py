import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from generators.circuit_merger import CircuitMerger
from generators.interactive_composer import (
    parse_parameter_overrides,
    pick_composition_parts,
)
from generators.lib.generator import BaseParams


class TestInteractiveComposer(unittest.TestCase):
    def test_pick_composition_parts_accepts_indexes_ranges_and_names(self):
        names = ["GHZ", "WState", "GraphState", "QFTGenerator"]

        picked = pick_composition_parts("1,3-4,wstate", names)

        self.assertEqual(picked, ["GHZ", "GraphState", "QFTGenerator", "WState"])

    def test_parse_parameter_overrides_accepts_key_value_and_literals(self):
        overrides = parse_parameter_overrides(
            "num_qubits=4,inverse=true,theta=0.25,adjacency=[[0,1],[1,0]]"
        )

        self.assertEqual(overrides["num_qubits"], 4)
        self.assertIs(overrides["inverse"], True)
        self.assertEqual(overrides["theta"], 0.25)
        self.assertEqual(overrides["adjacency"], [[0, 1], [1, 0]])

        literal_overrides = parse_parameter_overrides('{"num_qubits": 5, "do_swaps": false}')
        self.assertEqual(literal_overrides, {"num_qubits": 5, "do_swaps": False})

    def test_explicit_composition_generates_circuit(self):
        base_params = BaseParams(
            min_qubits=3,
            max_qubits=3,
            min_depth=1,
            max_depth=3,
            measure=False,
            seed=7,
        )
        merger = CircuitMerger(base_params)

        circuit = merger.generate_composed_circuit(
            [
                {"generator": "GHZ", "parameters": {"num_qubits": 3}},
                {
                    "generator": "QFTGenerator",
                    "parameters": {
                        "num_qubits": 3,
                        "inverse": False,
                        "do_swaps": False,
                        "entangled": False,
                    },
                },
            ],
        )

        self.assertEqual(circuit.num_qubits, 3)
        self.assertGreater(circuit.size(), 0)
        self.assertEqual(circuit.name, "InteractiveComposition_2gens")


if __name__ == "__main__":
    unittest.main()
