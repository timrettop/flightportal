# boot.py -- TRUSTED CORE. Load via USB. Never shipped as an OTA update.
#
# Decides who owns the filesystem, then gives ota.recovery a chance to roll
# back a bad update before code.py ever runs.
#
# Hold the DOWN button while resetting to keep CIRCUITPY writable over USB for
# local editing. Release it and the device owns the filesystem, which is what
# makes over-the-air updates possible.
#
# Everything here is wrapped in try/except on purpose: an uncaught exception in
# boot.py drops the board into safe mode, and safe mode cannot be fixed
# remotely.

import board
import digitalio
import storage

DEV_MODE = False

try:
    # BUTTON_DOWN has no external pull-up and reads low when pressed.
    btn = digitalio.DigitalInOut(board.BUTTON_DOWN)
    btn.switch_to_input(pull=digitalio.Pull.UP)
    DEV_MODE = not btn.value
    btn.deinit()
except Exception as e:  # noqa: BLE001 - never let boot.py fail
    print("boot: button check failed (%r), assuming device mode" % e)

try:
    if DEV_MODE:
        print("boot: DEV MODE -- USB writable, OTA disabled")
    else:
        storage.remount("/", readonly=False)
        print("boot: device mode -- OTA enabled, USB read-only")
except Exception as e:  # noqa: BLE001
    print("boot: remount failed: %r" % e)
    DEV_MODE = True

if not DEV_MODE:
    try:
        from ota import recovery

        recovery.check()
    except Exception as e:  # noqa: BLE001
        print("boot: recovery check failed: %r" % e)

# Optional: colour the status NeoPixel so you can tell the modes apart.
try:
    import neopixel

    px = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.1, auto_write=True)
    px[0] = (0, 0, 60) if DEV_MODE else (0, 40, 0)
except Exception:  # noqa: BLE001
    pass