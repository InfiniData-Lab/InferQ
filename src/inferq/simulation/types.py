from enum import Enum


class SimulationMethod(Enum):
    """Enumeration of available simulation methods in Qiskit"""

    STATEVECTOR = "statevector"
    MPS = "matrix_product_state"
    UNITARY = "unitary"
    DENSITY_MATRIX = "density_matrix"
    STABILIZER = "stabilizer"
    EXTENDED_STABILIZER = "extended_stabilizer"
    AUTOMATIC = "automatic"
    INFINI_QUANTUM = "infiniquantum"
