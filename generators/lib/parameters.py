import random
import networkx as nx


def num_qbits(min_qubits: int, max_qubits: int, seed: int = None) -> int:
    """
    Generate a random number of qubits between the specified limits.

    :param max_qubits: Maximum number of qubits.
    :param min_qubits: Minimum number of qubits.
    :param seed: Random seed for reproducibility (if None, uses current random state).
    :return: Random number of qubits.
    """
    return random.randint(min_qubits, max_qubits)


def depth(min_depth: int, max_depth: int, seed: int = None) -> int:
    """
    Generate a random depth for a quantum circuit.

    :param min_depth: Minimum depth of the circuit.
    :param max_depth: Maximum depth of the circuit.
    :param seed: Random seed for reproducibility.
    :return: Random depth value.
    """
  
    return random.randint(min_depth, max_depth)


def adjacency_graph(
    num_qubits: int, seed: int = None, p: float = 0.5, return_edges: bool = False
) -> list[list[int]]:
    """
    Generate a random graph using NetworkX's G(n, p) model,
    returning either an adjacency matrix or adjacency list.

    :param num_qubits: Number of nodes (qubits).
    :param seed: Random seed for reproducibility.
    :param p: Edge‐presence probability (default 0.5).
    :param adjacency_list: If True, return adjacency list; else adjacency matrix.
    :return: Either a nested list-of-lists adjacency matrix (0/1)
             or adjacency list ([[neighbors_of_0], [neighbors_of_1], …]).
    """
    G = nx.gnp_random_graph(num_qubits, p, seed=seed, directed=False)

    if return_edges:
        # Return each undirected edge once as [u, v]
        return [[u, v] for u, v in G.edges()]
    else:
        # Convert to dense adjacency matrix
        A = nx.to_numpy_array(G, dtype=int)
        return A.astype(int).tolist()


def reps(min_reps: int, max_reps: int, seed: int = None) -> int:
    """
    Generate a random number of repetitions for a quantum circuit.

    :param min_reps: Minimum number of repetitions.
    :param max_reps: Maximum number of repetitions.
    :param seed: Random seed for reproducibility.
    :return: Random number of repetitions.
    """
  
    return random.randint(min_reps, max_reps)


def entanglement_pattern(num_qubits: int, seed: int = None) -> str:
    """
    Generate a random entanglement pattern for a quantum circuit.

    :param num_qubits: Number of qubits in the circuit.
    :param seed: Random seed for reproducibility.
    :return: Entanglement pattern as a string.
    """
    
    if random.choice([False, True]):
        return entanglement_pattern_string(seed)
    else:
        g = adjacency_graph(
            num_qubits,
            seed,
            p=random.uniform(0.1, 0.9),  # Random probability for edge creation
            return_edges=True,
        )
        import logging
        logger = logging.getLogger(__name__)
        logger.debug("Generated adjacency graph:", g)
        return g


def entanglement_pattern_string(seed: int = None) -> str:
    """
    Generate a random entanglement pattern for a quantum circuit.

    :param seed: Random seed for reproducibility.
    :return: Entanglement pattern as a string.
    """
    patterns = ["linear", "full", "circular", "reverse_linear"]
  
    return random.choice(patterns)


def random_parameter_values(
    num_params: int,
    seed: int = None,
    min_val: float = 0.0,
    max_val: float = 2 * 3.14159,
) -> list[float]:
    """
    Generate a list of random parameter values for quantum circuits.

    :param num_params: Number of parameters needed.
    :param seed: Random seed for reproducibility.
    :param min_val: Minimum value for parameters (default: 0.0).
    :param max_val: Maximum value for parameters (default: 2π).
    :return: List of random parameter values.
    """
  
    return [round(random.uniform(min_val, max_val),3) for _ in range(num_params)]


def evaluation_qubits(min_eval: int = 2, max_eval: int = 6, seed: int = None) -> int:
    """
    Generate a random number of evaluation qubits for amplitude estimation.

    :param min_eval: Minimum number of evaluation qubits.
    :param max_eval: Maximum number of evaluation qubits.
    :param seed: Random seed for reproducibility.
    :return: Random number of evaluation qubits.
    """
  
    return random.randint(min_eval, max_eval)


def demo_theta_value(
    seed: int = None, min_theta: float = 0.1, max_theta: float = 1.5
) -> float:
    """
    Generate a random theta value for amplitude estimation demo mode.

    :param seed: Random seed for reproducibility.
    :param min_theta: Minimum theta value (default: 0.1).
    :param max_theta: Maximum theta value (default: 1.5).
    :return: Random theta value.
    """
  
    return random.uniform(min_theta, max_theta)


def oracle_type_choice(seed: int = None) -> str:
    """
    Randomly choose between balanced and constant oracle types.

    :param seed: Random seed for reproducibility.
    :return: Random oracle type ('balanced' or 'constant').
    """
  
    return random.choice(["balanced", "constant"])


def random_bitstring(n: int, seed: int = None) -> str:
    """
    Generate a random non-zero bitstring of length n.

    :param n: Length of the bitstring.
    :param seed: Random seed for reproducibility.
    :return: Random bitstring as a string of 0s and 1s.
    """
  
    # Ensure non-zero bitstring for balanced oracle
    return format(random.randint(1, 2**n - 1), f"0{n}b")


def constant_output_choice(seed: int = None) -> int:
    """
    Randomly choose between 0 and 1 for constant oracle output.

    :param seed: Random seed for reproducibility.
    :return: Random constant output (0 or 1).
    """
  
    return random.choice([0, 1])


def grover_target_bitstring(n: int, seed: int = None) -> str:
    """
    Generate a random target bitstring for Grover search.

    :param n: Length of the bitstring.
    :param seed: Random seed for reproducibility.
    :return: Random bitstring as a string of 0s and 1s.
    """
  
    return format(random.randrange(2**n), f"0{n}b")


def grover_iterations(n: int, seed: int = None, use_optimal: bool = True) -> int:
    """
    Generate number of Grover iterations.

    :param n: Number of qubits.
    :param seed: Random seed for reproducibility.
    :param use_optimal: If True, use optimal iterations. If False, add some randomness.
    :return: Number of Grover iterations.
    """
    import math

    optimal = int(math.floor((math.pi / 4) * math.sqrt(2**n)))

    if use_optimal:
        return max(1, optimal)
    else:
        # Add some randomness around the optimal value
        variation = max(1, optimal // 4)
        return max(1, optimal + random.randint(-variation, variation))


def qft_inverse_flag(seed: int = None) -> bool:
    """
    Generate a random boolean flag for QFT inverse mode.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        bool: True for inverse QFT, False for forward QFT.
    """
  
    return random.choice([True, False])


def qft_swaps_flag(seed: int = None) -> bool:
    """
    Generate a random boolean flag for QFT swaps.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        bool: True to include qubit-reversal swaps, False to omit them.
    """
  
    # Bias towards including swaps (more common use case)
    return random.choices([True, False], weights=[0.8, 0.2])[0]


def qft_entanglement_flag(seed: int = None) -> bool:
    """
    Generate a random boolean flag for QFT entanglement mode.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        bool: True for entangled QFT, False for regular QFT.
    """
  
    # Bias towards non-entangled (regular QFT is more common)
    return random.choices([True, False], weights=[0.3, 0.7])[0]


def qnn_feature_map_type(seed: int = None) -> str:
    """
    Generate a random feature map type for QNN.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        str: Feature map type ('ZFeatureMap', 'ZZFeatureMap', 'PauliFeatureMap').
    """
  
    return random.choice(["ZFeatureMap", "ZZFeatureMap", "PauliFeatureMap"])


def qnn_ansatz_type(seed: int = None) -> str:
    """
    Generate a random ansatz type for QNN.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        str: Ansatz type ('RealAmplitudes', 'EfficientSU2', 'TwoLocal').
    """
  
    return random.choice(["RealAmplitudes", "EfficientSU2", "TwoLocal"])


def qnn_reps(seed: int = None, min_reps: int = 1, max_reps: int = 3) -> int:
    """
    Generate a random number of repetitions for QNN ansatz.

    Args:
        seed: Random seed for reproducibility.
        min_reps: Minimum number of repetitions.
        max_reps: Maximum number of repetitions.

    Returns:
        int: Number of repetitions.
    """
  
    return random.randint(min_reps, max_reps)


def qwalk_steps(seed: int = None, min_steps: int = 1, max_steps: int = 10) -> int:
    """
    Generate a random number of quantum walk steps.

    Args:
        seed: Random seed for reproducibility.
        min_steps: Minimum number of steps.
        max_steps: Maximum number of steps.

    Returns:
        int: Number of quantum walk steps.
    """
  
    return random.randint(min_steps, max_steps)


def qwalk_coin_preparation_type(seed: int = None) -> str:
    """
    Generate a random coin state preparation type for quantum walk.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        str: Coin preparation type ('hadamard', 'x', 'y', 'none').
    """
  
    return random.choice(["hadamard", "x", "y", "none"])


def qwalk_graph_size(num_qubits: int, seed: int = None) -> int:
    """
    Generate graph size for quantum walk (number of graph nodes).

    Args:
        num_qubits: Total number of qubits available.
        seed: Random seed for reproducibility.

    Returns:
        int: Number of graph nodes (num_qubits - 1 for coin qubit).
    """
  
    # Reserve 1 qubit for coin, rest for graph nodes
    return max(1, num_qubits - 1)


def qaoa_layers(seed: int = None, min_layers: int = 1, max_layers: int = 5) -> int:
    """
    Generate a random number of QAOA layers (p).

    Args:
        seed: Random seed for reproducibility.
        min_layers: Minimum number of layers.
        max_layers: Maximum number of layers.

    Returns:
        int: Number of QAOA layers.
    """
  
    return random.randint(min_layers, max_layers)


def qaoa_gamma_parameters(p: int, seed: int = None) -> list[float]:
    """
    Generate random gamma parameters for QAOA.

    Args:
        p: Number of QAOA layers.
        seed: Random seed for reproducibility.

    Returns:
        list[float]: List of gamma values.
    """
  
    import math

    return [random.uniform(0, math.pi) for _ in range(p)]


def qaoa_beta_parameters(p: int, seed: int = None) -> list[float]:
    """
    Generate random beta parameters for QAOA.

    Args:
        p: Number of QAOA layers.
        seed: Random seed for reproducibility.

    Returns:
        list[float]: List of beta values.
    """
  
    import math

    return [random.uniform(0, math.pi) for _ in range(p)]


def qaoa_adjacency_matrix(
    num_qubits: int, seed: int = None, edge_prob: float = 0.5
) -> list[list[float]]:
    """
    Generate a random adjacency matrix for QAOA Max-Cut problems.
    Guarantees at least one edge exists (never all zeros).

    Args:
        num_qubits: Number of qubits (size of adjacency matrix).
        seed: Random seed for reproducibility.
        edge_prob: Probability of edge existence.

    Returns:
        list[list[float]]: Symmetric adjacency matrix with random weights.
    """
  

    # Initialize matrix with zeros
    adj = [[0.0 for _ in range(num_qubits)] for _ in range(num_qubits)]

    # Fill upper triangle with random edges
    has_edge = False
    for i in range(num_qubits):
        for j in range(i + 1, num_qubits):
            if random.random() < edge_prob:
                # Random weight between 0.1 and 2.0
                weight = random.uniform(0.1, 2.0)
                adj[i][j] = weight
                adj[j][i] = weight  # Symmetric
                has_edge = True

    # Ensure at least one edge exists (never all zeros)
    if not has_edge and num_qubits > 1:
        # Add a random edge between two random nodes
        i = random.randint(0, num_qubits - 2)
        j = random.randint(i + 1, num_qubits - 1)
        weight = random.uniform(0.1, 2.0)
        adj[i][j] = weight
        adj[j][i] = weight

    return adj


def qaoa_problem_type(seed: int = None) -> str:
    """
    Generate a random QAOA problem type.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        str: Problem type ('maxcut', 'custom').
    """
  
    # Bias towards MaxCut as it's more common
    return random.choices(["maxcut", "custom"], weights=[0.8, 0.2])[0]


def qpe_evaluation_qubits(
    seed: int = None, min_eval: int = 2, max_eval: int = 8
) -> int:
    """
    Generate a random number of evaluation qubits for QPE.

    Args:
        seed: Random seed for reproducibility.
        min_eval: Minimum number of evaluation qubits.
        max_eval: Maximum number of evaluation qubits.

    Returns:
        int: Number of evaluation qubits.
    """
  
    return random.randint(min_eval, max_eval)


def qpe_approximation_degree(seed: int = None, max_degree: int = 5) -> int:
    """
    Generate a random approximation degree for QPE QFT.

    Args:
        seed: Random seed for reproducibility.
        max_degree: Maximum approximation degree.

    Returns:
        int: Approximation degree (0 = exact, higher = more approximation).
    """
  
    # Bias towards lower degrees (0-2 are most common)
    weights = [0.3, 0.3, 0.2] + [0.2 / (max_degree - 2)] * max(0, max_degree - 2)
    degrees = list(range(max_degree + 1))
    return random.choices(degrees, weights=weights[: len(degrees)])[0]


def qpe_eigenphase_value(seed: int = None) -> float:
    """
    Generate a random eigenphase value for QPE demo.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        float: Eigenphase value in [0, 1).
    """
  
    # Generate a phase that's likely to be representable with limited precision
    # Use fractions with small denominators for better QPE results
    denominators = [2, 4, 8, 16, 32, 64, 128, 256]
    denom = random.choice(denominators)
    numerator = random.randint(1, denom - 1)
    return numerator / denom


def qpe_system_qubits(seed: int = None, min_sys: int = 1, max_sys: int = 3) -> int:
    """
    Generate a random number of system qubits for QPE.

    Args:
        seed: Random seed for reproducibility.
        min_sys: Minimum number of system qubits.
        max_sys: Maximum number of system qubits.

    Returns:
        int: Number of system qubits.
    """
  
    return random.randint(min_sys, max_sys)


def vqe_ansatz_type(seed: int = None) -> str:
    """
    Generate a random ansatz type for VQE.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        str: Ansatz type ('RealAmplitudes', 'EfficientSU2', 'TwoLocal').
    """
  
    ansatz_types = ["RealAmplitudes", "EfficientSU2", "TwoLocal"]
    return random.choice(ansatz_types)


def vqe_reps(seed: int = None, min_reps: int = 1, max_reps: int = 4) -> int:
    """
    Generate a random number of repetitions for VQE ansatz.

    Args:
        seed: Random seed for reproducibility.
        min_reps: Minimum number of repetitions.
        max_reps: Maximum number of repetitions.

    Returns:
        int: Number of repetitions.
    """
  
    return random.randint(min_reps, max_reps)


def vqe_entanglement_pattern(seed: int = None) -> str:
    """
    Generate a random entanglement pattern for VQE ansatz.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        str: Entanglement pattern ('full', 'linear', 'circular', 'pairwise').
    """
  
    patterns = ["full", "linear", "circular", "pairwise"]
    # Bias towards 'full' as it's most common
    weights = [0.4, 0.2, 0.2, 0.2]
    return random.choices(patterns, weights=weights)[0]


def vqe_parameter_prefix(seed: int = None) -> str:
    """
    Generate a random parameter prefix for VQE.

    Args:
        seed: Random seed for reproducibility.

    Returns:
        str: Parameter prefix ('θ', 'phi', 'alpha', 'beta').
    """
  
    prefixes = ["θ", "phi", "alpha", "beta"]
    # Bias towards 'θ' as it's most common
    weights = [0.5, 0.2, 0.15, 0.15]
    return random.choices(prefixes, weights=weights)[0]
