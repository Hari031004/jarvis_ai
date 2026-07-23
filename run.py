"""Standalone entry point for the JARVIS assistant.

Usage:
    python run.py

This file adds its own directory to sys.path so the assistant
package is importable without installing anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).parent.resolve()
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from assistant.main import main

if __name__ == "__main__":
    main()
