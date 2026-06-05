"""Pytest setup — ensure the repo root is importable (engine.*, dashboard.*, evaluate)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
