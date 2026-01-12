import os
import numpy as np
from qiskit import qpy, transpile, quantum_info
from qiskit_aer import AerSimulator

# Folder with qpy circuits
qpy_folder = "./circuits/00"
qpy_files = [f for f in os.listdir(qpy_folder) if f.endswith(".qpy")]

backend = AerSimulator(method="statevector")

def per_qubit_entropy_fast(statevector):
    """Vectorized per-qubit von Neumann entropy (very fast)."""
    n = int(np.log2(len(statevector)))
    # Convert statevector to probabilities
    probs = np.abs(statevector)**2
    # Create a 2^n x n binary index array
    bits = ((np.arange(2**n)[:, None] >> np.arange(n-1, -1, -1)) & 1)
    # Sum probabilities where bit=0 and bit=1 per qubit
    p0 = np.sum(probs[:, None] * (bits == 0), axis=0)
    p1 = np.sum(probs[:, None] * (bits == 1), axis=0)
    p = np.vstack([p0, p1])
    p = np.clip(p, 1e-12, 1)
    S = -np.sum(p * np.log2(p), axis=0)
    return S

for file in qpy_files:
    with open(os.path.join(qpy_folder, file), "rb") as f:
        circuit = qpy.load(f)[0]

    circuit = circuit.remove_final_measurements(inplace=False)
    circuit.save_statevector()
    if len(circuit.qubits)>15:
        continue
    tcirc = transpile(circuit, backend)
    result = backend.run(tcirc).result()
    state = result.get_statevector(tcirc).data


    entropy=quantum_info.entropy(state)
    entropies = per_qubit_entropy_fast(state)
    print(f"\nCircuit: {file}")
    print(f"  Total Qiskit von Neumann entropy: ≈ {entropy:.6f}")
    for q, S in enumerate(entropies):
        print(f"  Qubit {q}: von Neumann entropy ≈ {S:.6f}")
