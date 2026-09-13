"""Content-addressed local circuit storage.

A circuit's identity is the SHA-256 of its canonical QPY serialization, computed by
:func:`compute_circuit_hash`. Everything else here — the on-disk layout, the
duplicate detector, the QPY reader — keys off that hash, so the same circuit always
lands in the same place regardless of which run produced it.
"""

from .duplicates import (
    DuplicateDetector,
    get_duplicate_detector,
    initialize_duplicate_detection,
    is_circuit_duplicate,
)
from .hashing import (
    compute_circuit_hash,
    compute_circuit_hash_simple,
    get_hash_info,
    verify_circuit_hash,
)
from .local import get_circuit_info, load_circuit_locally, save_circuit_locally
from .qpy import circuit_from_qpy_programs, load_circuit

__all__ = [
    "DuplicateDetector",
    "circuit_from_qpy_programs",
    "compute_circuit_hash",
    "compute_circuit_hash_simple",
    "get_circuit_info",
    "get_duplicate_detector",
    "get_hash_info",
    "initialize_duplicate_detection",
    "is_circuit_duplicate",
    "load_circuit",
    "load_circuit_locally",
    "save_circuit_locally",
    "verify_circuit_hash",
]
