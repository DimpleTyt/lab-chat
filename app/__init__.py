"""lab-chat backend package.

Keeps the project root importable so `shared.*` works no matter how the app
is launched (uvicorn from root, tools/*.py, pytest from elsewhere).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

__all__ = ["ROOT"]
