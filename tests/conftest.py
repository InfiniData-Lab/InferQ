"""Shared pytest configuration.

Puts the repository root on ``sys.path`` so tests import the packages the same
way the entry points do, without per-file ``sys.path`` manipulation.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
