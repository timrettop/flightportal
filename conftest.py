import os
import sys
import types

# code.py (required by CircuitPython) shadows Python's stdlib `code` module
# whenever the repo root is on sys.path. pytest's debugging plugin imports
# pdb -> code during startup, which then crashes on `import board`. We can't
# rename code.py, so make flightlogic importable and leave it at that.
sys.path.insert(0, os.path.dirname(__file__))


# --- CircuitPython stubs -------------------------------------------------
# ota/state.py and ota/updater.py import `microcontroller` at module level, so
# it has to exist before any test module imports them.


def _no_reset():
    raise AssertionError("microcontroller.reset() called; test did not expect a reset")


if "microcontroller" not in sys.modules:
    _mc = types.ModuleType("microcontroller")
    _mc.nvm = bytearray(64)
    _mc.reset = _no_reset
    sys.modules["microcontroller"] = _mc


# ota/doorbell.py imports adafruit_minimqtt. Stub just enough that the module
# imports; the tests inject their own fake client.
if "adafruit_minimqtt" not in sys.modules:
    _pkg = types.ModuleType("adafruit_minimqtt")
    _mod = types.ModuleType("adafruit_minimqtt.adafruit_minimqtt")

    class _StubMQTT:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.on_message = None

        def is_connected(self):
            return False

        def connect(self):
            raise OSError("stub broker")

        def subscribe(self, feed):
            pass

        def loop(self, timeout=1):
            pass

        def disconnect(self):
            pass

    _mod.MQTT = _StubMQTT
    _pkg.adafruit_minimqtt = _mod
    sys.modules["adafruit_minimqtt"] = _pkg
    sys.modules["adafruit_minimqtt.adafruit_minimqtt"] = _mod
