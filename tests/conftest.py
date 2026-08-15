"""Pytest configuration shared by all tests.

Adds the project's ``src/`` directory to ``sys.path`` so tests can
import the O4 modules directly (they import each other by bare module
name, as they do when Ortho4XP runs with ``src`` as its working
directory) without installing the package.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.normpath(os.path.join(_HERE, "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
