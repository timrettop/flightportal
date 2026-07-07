import os
import sys

# code.py (required by CircuitPython) shadows Python's stdlib `code` module
# whenever the repo root is on sys.path. pytest's debugging plugin imports
# pdb -> code during startup, which then crashes on `import board`. We can't
# rename code.py, so make flightlogic importable and leave it at that.
sys.path.insert(0, os.path.dirname(__file__))
