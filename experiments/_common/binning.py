"""Memory-bin assignment shared by the OOC manifest builders and sampler.

Circuits are binned by qubit count because Aer statevector memory is
``2^N * 16`` bytes, so the qubit count alone predicts which memory caps make
Aer run out of memory. The bin names are part of the manifest schema consumed
by ``experiments/ooc/run_experiment.py`` and must not change.
"""
from __future__ import annotations

from collections.abc import Sequence

BIN_EDGES_DEFAULT = [25, 28, 30, 31]

BIN_NAMES = (
    "B0_trivial",
    "B1_aer_ok_all_caps",
    "B2_aer_fails_at_4",
    "B3_aer_fails_at_8",
    "B4_aer_impossible",
)


def assign_bin(num_qubits: int, edges: Sequence[int]) -> tuple[str, int]:
    """Return the ``(bin_name, bin_order)`` for a circuit of ``num_qubits``.

    Args:
        num_qubits: Qubit count of the circuit.
        edges: Four ascending cut points ``[e1, e2, e3, e4]``; a circuit falls
            in bin ``i`` when its qubit count is below ``edges[i]``, and in the
            final bin when it is at or above ``edges[3]``.

    Returns:
        The bin name and its zero-based order.
    """
    for order, (name, edge) in enumerate(zip(BIN_NAMES, edges, strict=False)):
        if num_qubits < edge:
            return name, order
    return BIN_NAMES[-1], len(BIN_NAMES) - 1
