from qiskit import QuantumCircuit
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import num_qbits, adjacency_graph


class GraphState(Generator):
    """
    Class to generate a graph state circuit from an adjacency matrix.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)

    def generate(self, adjacency: list[list[int]]) -> QuantumCircuit:
        """Graph state from adjacency matrix."""
        n = len(adjacency)
        qc = QuantumCircuit(n, name="GraphState")
        for i in range(n):
            qc.h(i)
        for i in range(n):
            for j in range(i + 1, n):
                if adjacency[i][j]:
                    qc.cz(i, j)
        if self.measure:
            qc.measure_all()
        return qc

    def generate_parameters(self) -> list[list[int]]:
        self.measure = self.base_params.measure
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )
        self.adjacency = adjacency_graph(
            self.num_qubits,
            seed=self.base_params.seed,
            p=0.5,  # Default probability for edge creation
        )
        return self.adjacency


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=5, min_qubits=2, max_depth=10, min_depth=1, measure=False
    )
    graph_state_generator = GraphState(params)
    adjacency_matrix = graph_state_generator.generate_parameters()
    graph_state_circuit = graph_state_generator.generate(adjacency_matrix)
    print(graph_state_circuit)
