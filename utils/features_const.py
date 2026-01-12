FEATURES_LIST = {
    # Metadata
    "qpy_sha256": "CHAR(64)",
    "blob_path": "NVARCHAR(260)",
    "name": "NVARCHAR(255)", 
    
    # Static Features
    "num_qubits": "INT",
    "width": "INT",
    "depth": "INT",
    "two_qubit_gate_count": "INT",
    "two_qubit_gate_percentage": "FLOAT",
    "pauli_gate_count": "INT",
    "density_score": "FLOAT",
    "idling_score": "FLOAT",
    "gate_counts": "TEXT", # JSON string

    # Dynamic Features
    "sparsity": "FLOAT",
    "locality_ratio": "FLOAT",
    "shannon_entropy": "FLOAT",
    "von_neumann_entropy": "LIST[FLOAT]",

    # Graph Features (IG)
    "igdepth": "INT",
    "radius": "FLOAT",
    "diameter": "FLOAT",
    "max_degree": "INT",
    "min_cut_upper": "INT",
    "edge_count": "INT",
    "node_count": "INT",
    "average_degree": "FLOAT",
    "std_dev_adjacency_matrix": "FLOAT",
    "central_point_of_dominance": "FLOAT",
    "average_clustering_coefficient": "FLOAT",
    "average_shortest_path_length": "FLOAT",
    
    # Complex Graph Features
    "connected_components": "TEXT",
    "core_number": "TEXT",
    "pagerank": "TEXT"
}

SQL_FEATURES = [
    "SELECT", 
    "INSERT", 
    "UPDATE", 
    "DELETE",
    "WHERE", 
    "GROUP_BY", 
    "HAVING", 
    "ORDER_BY", 
    "LIMIT", 
    "CTE",
    "UNION", 
    "INTERSECT", 
    "EXCEPT",
    "AGG_FUNC", 
    "AND", 
    "OR", 
    "NOT", 
    "EQ_PRED", 
    "RANGE_PRED", 
    "IN_PRED", 
    "LIKE_PRED",
    "NUM_UNIQUE_JOIN_EDGES", 
    "NUM_JOIN_OCCURRENCES"
]