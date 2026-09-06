# ota/doorbell.py
#
# Subscribes to an Adafruit IO feed so a release can push the device into
# checking immediately instead of waiting for the next poll.
#
# The message carries no authority. Its contents are ignored entirely: all it
# does is trigger the same signed-manifest check that the timer would have run
# anyway. A compromised broker can make the device check for updates slightly
# more often, and nothing else. Never take a URL or a version number from it.

import time

import adafruit_minimqtt.adafruit_minimqtt as MQTT

from ota import updater


class Doorbell:
    def __init__(
        self,
        socket_pool,
        ssl_context,
        aio_user,
        aio_key,
        feed="ota",
        poll_interval=3600,
        log=print,
        on_checking=None,
    ):
        self.feed = "%s/feeds/%s" % (aio_user, feed)
        self.poll_interval = poll_interval
        self.log = log
        self.on_checking = on_checking
        self._ring = False
        self._next_poll = 0
        self._next_retry = 0

        self.client = MQTT.MQTT(
            broker="io.adafruit.com",
            port=8883,
            username=aio_user,
            password=aio_key,
            socket_pool=socket_pool,
            ssl_context=ssl_context,
            is_ssl=True,
            keep_alive=120,
        )
        self.client.on_message = self._on_message

    def _on_message(self, client, topic, message):
        self.log("ota: doorbell rang")
        self._ring = True

    def _ensure_connected(self):
        if self.client.is_connected():
            return True
        now = time.monotonic()
        if now < self._next_retry:
            return False
        try:
            self.client.connect()
            self.client.subscribe(self.feed)
            self.log("ota: doorbell connected")
            return True
        except Exception as e:  # noqa: BLE001 - MQTT must never kill the display
            self.log("ota: doorbell connect failed: %r" % e)
            self._next_retry = now + 60
            return False

    def poll(self, session):
        """Call from your main loop. Returns True if an update was applied.

        On success the board resets, so in practice this returns True only if
        you passed reset=False into the updater.
        """
        try:
            if self._ensure_connected():
                self.client.loop(timeout=0.1)
        except Exception as e:  # noqa: BLE001
            self.log("ota: doorbell loop failed: %r" % e)
            try:
                self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._next_retry = time.monotonic() + 60

        now = time.monotonic()
        due = self._ring or now >= self._next_poll
        if not due:
            return False

        self._ring = False
        self._next_poll = now + self.poll_interval

        if self.on_checking is not None:
            try:
                self.on_checking()
            except Exception as e:  # noqa: BLE001 - a display glitch must not block the check
                self.log("ota: on_checking callback failed: %r" % e)

        return updater.check_and_apply(session, log=self.log)