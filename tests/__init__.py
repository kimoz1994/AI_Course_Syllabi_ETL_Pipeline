"""Test package.

Makes ``src/`` importable without installation (local environments where
``pip install -e .`` is unavailable); CI installs the package properly and
this becomes a harmless no-op.
"""

import sys
from pathlib import Path

_src = Path(__file__).resolve().parents[1] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
