"""Tests for ota/doorbell.py.

The doorbell must never take down the display, so most of these are about what
happens when MQTT misbehaves. A fake clock is injected because the whole module
is timer logic.
"""
import types

import pytest

from ota import doorbell


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.on_message = None
        self.connected = False
        self.subscriptions = []
        self.loops = 0
        self.disconnects = 0
        self.connect_error = None
        self.loop_error = None

    def is_connected(self):
        return self.connected

    def connect(self):
        if self.connect_error:
            raise self.connect_error
        self.connected = True

    def subscribe(self, feed):
        self.subscriptions.append(feed)

    def loop(self, timeout=1):
        self.loops += 1
        if self.loop_error:
            raise self.loop_error

    def disconnect(self):
        self.disconnects += 1
        self.connected = False


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(doorbell.time, "monotonic", c)
    return c


@pytest.fixture
def client(monkeypatch):
    made = []

    def factory(**kwargs):
        c = FakeClient(**kwargs)
        made.append(c)
        return c

    monkeypatch.setattr(doorbell, "MQTT", types.SimpleNamespace(MQTT=factory))
    return made


@pytest.fixture
def checks(monkeypatch):
    """Record calls to updater.check_and_apply; report 'nothing applied'."""
    calls = []

    def fake(session, log=print, on_installing=None):
        calls.append(session)
        return False

    monkeypatch.setattr(doorbell.updater, "check_and_apply", fake)
    return calls


@pytest.fixture
def bell(clock, client, checks):
    return doorbell.Doorbell(
        socket_pool=object(),
        ssl_context=object(),
        aio_user="tim",
        aio_key="secret",
        poll_interval=3600,
        mqtt_loop_interval=5,
        log=lambda *a: None,
    )


# ---- wiring ----
def test_subscribes_to_the_users_own_feed(bell, client):
    bell.poll(session=object())
    assert client[0].subscriptions == ["tim/feeds/ota"]


def test_connects_over_tls(bell, client):
    assert client[0].kwargs["port"] == 8883
    assert client[0].kwargs["is_ssl"] is True


# ---- poll timing ----
def test_checks_for_updates_on_the_first_poll(bell, checks):
    session = object()
    bell.poll(session)
    assert checks == [session]


def test_does_not_check_again_until_the_interval_elapses(bell, clock, checks):
    bell.poll(object())
    for _ in range(5):
        clock.advance(600)
        bell.poll(object())
    assert len(checks) == 1


def test_checks_again_once_the_interval_elapses(bell, clock, checks):
    bell.poll(object())
    clock.advance(3601)
    bell.poll(object())
    assert len(checks) == 2


# ---- the doorbell itself ----
def test_a_ring_forces_an_immediate_check(bell, clock, checks):
    bell.poll(object())          # consumes the initial due-now check
    clock.advance(10)
    bell._on_message(None, "tim/feeds/ota", "42")
    bell.poll(object())
    assert len(checks) == 2


def test_a_ring_is_consumed_not_repeated(bell, clock, checks):
    bell.poll(object())
    bell._on_message(None, "tim/feeds/ota", "42")
    bell.poll(object())
    clock.advance(10)
    bell.poll(object())
    assert len(checks) == 2


def test_message_contents_are_ignored(bell, clock, checks, monkeypatch):
    """The payload carries no authority: it must not reach the updater."""
    seen = []
    monkeypatch.setattr(
        doorbell.updater, "check_and_apply",
        lambda session, log=print, on_installing=None: seen.append(
            (session, log, on_installing)
        ) or False,
    )
    bell._on_message(None, "tim/feeds/ota", "https://evil.invalid/manifest.json")
    bell.poll(object())
    for call in seen:
        assert "evil.invalid" not in repr(call)


def test_returns_true_when_an_update_was_applied(bell, monkeypatch):
    monkeypatch.setattr(
        doorbell.updater, "check_and_apply",
        lambda session, log=print, on_installing=None: True,
    )
    assert bell.poll(object()) is True


def test_on_installing_is_passed_through(clock, client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        doorbell.updater, "check_and_apply",
        lambda session, log=print, on_installing=None: seen.update(
            cb=on_installing
        ) or False,
    )
    cb = lambda: None
    bell = doorbell.Doorbell(
        socket_pool=object(), ssl_context=object(),
        aio_user="tim", aio_key="secret",
        log=lambda *a: None, on_installing=cb,
    )
    bell.poll(object())
    assert seen["cb"] is cb


# ---- failure containment ----
def test_a_failed_connect_does_not_raise(bell, client):
    client[0].connect_error = OSError("no route to host")
    bell.poll(object())  # must not raise


def test_a_failed_connect_still_lets_the_timed_check_run(bell, client, checks):
    client[0].connect_error = OSError("no route to host")
    bell.poll(object())
    assert len(checks) == 1, "MQTT being down must not stop polled updates"


def test_connect_failures_are_backed_off(bell, client, clock):
    client[0].connect_error = OSError("no route to host")
    bell.poll(object())
    for _ in range(10):
        clock.advance(5)
        bell.poll(object())
    assert client[0].disconnects == 0
    clock.advance(60)
    bell.poll(object())


def test_a_loop_error_disconnects_and_does_not_raise(bell, client, clock):
    bell.poll(object())
    assert client[0].connected is True
    client[0].loop_error = RuntimeError("socket exploded")
    clock.advance(10)
    bell.poll(object())
    assert client[0].disconnects == 1


def test_loop_is_throttled_by_mqtt_loop_interval(bell, client, clock):
    """client.loop() blocks for up to a second, so it must not run every call."""
    for _ in range(20):
        clock.advance(1)
        bell.poll(object())
    assert client[0].loops <= 5


def test_a_disconnect_that_itself_fails_is_survivable(bell, client, clock):
    bell.poll(object())
    client[0].loop_error = RuntimeError("socket exploded")
    client[0].disconnect = lambda: (_ for _ in ()).throw(OSError("already gone"))
    clock.advance(10)
    bell.poll(object())  # must not raise
