"""Tests für den APNs-Live-Activity-Channel.

Wir mocken die ``aioapns``-Library komplett, damit:
    - keine echte Apple-Verbindung versucht wird,
    - die Tests ohne installierte Dependency lauffähig sind.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fake aioapns module – wird vor dem Import des Channels installiert.
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    status: str = "200"
    description: str | None = None


class _FakeAPNs:
    last_instance: _FakeAPNs | None = None

    def __init__(self, **kwargs: Any) -> None:  # noqa: D401
        self.kwargs = kwargs
        self.sent: list[Any] = []
        self._response = _FakeResponse(status="200")
        _FakeAPNs.last_instance = self

    def queue_response(self, response: _FakeResponse) -> None:
        self._response = response

    async def send_notification(self, request: Any) -> _FakeResponse:
        self.sent.append(request)
        return self._response


class _FakeNotificationRequest:
    def __init__(self, **kwargs: Any) -> None:
        self.device_token = kwargs.get("device_token")
        self.message = kwargs.get("message")
        self.priority = kwargs.get("priority")
        self.push_type = kwargs.get("push_type")
        self.topic = kwargs.get("topic")


def _install_fake_aioapns() -> None:
    fake = types.ModuleType("aioapns")
    fake.APNs = _FakeAPNs  # type: ignore[attr-defined]
    fake.NotificationRequest = _FakeNotificationRequest  # type: ignore[attr-defined]
    sys.modules["aioapns"] = fake


_install_fake_aioapns()


# Jetzt erst importieren – Channel ruft aioapns lazy auf.
from app.channels import apns_liveactivity  # noqa: E402


@pytest.fixture(autouse=True)
def _configure_apns(monkeypatch):
    """Setzt Pflicht-Settings, sodass _ensure_configured nicht fehlschlägt.

    ``APNS_BUNDLE_ID`` muss in der Realität exakt der iOS-Main-App-Bundle-ID
    entsprechen (dev/internal/production unterschiedlich – siehe
    ``app.config.ts`` der Gäste-App). Hier verwenden wir absichtlich einen
    Platzhalter, weil die Tests nur die Header-Konstruktion und
    Fehlerbehandlung verifizieren – nicht die echte APNs-Topic-Auflösung.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "APNS_KEY_ID", "TESTKEYID")
    monkeypatch.setattr(settings, "APNS_TEAM_ID", "TESTTEAMID")
    monkeypatch.setattr(settings, "APNS_BUNDLE_ID", "de.servecta.gastropilot.app")
    monkeypatch.setattr(settings, "APNS_AUTH_KEY_PATH", "/tmp/fake.p8")
    monkeypatch.setattr(settings, "APNS_USE_SANDBOX", True)
    apns_liveactivity.reset_client_for_tests()
    yield
    apns_liveactivity.reset_client_for_tests()


@pytest.mark.asyncio
async def test_send_live_activity_update_builds_correct_payload():
    result = await apns_liveactivity.send_live_activity_update(
        activity_push_token="abc123def456",
        content_state={"status": "preparing", "eta_minutes": 12},
    )

    assert result.success is True
    assert result.status_code == 200

    instance = _FakeAPNs.last_instance
    assert instance is not None
    assert instance.kwargs["topic"] == "de.servecta.gastropilot.app.push-type.liveactivity"
    assert instance.kwargs["use_sandbox"] is True

    sent = instance.sent[-1]
    assert sent.device_token == "abc123def456"
    assert sent.priority == 10
    assert sent.push_type == "liveactivity"
    assert sent.topic == "de.servecta.gastropilot.app.push-type.liveactivity"

    aps = sent.message["aps"]
    assert aps["event"] == "update"
    assert aps["content-state"] == {"status": "preparing", "eta_minutes": 12}
    assert isinstance(aps["timestamp"], int)


@pytest.mark.asyncio
async def test_send_live_activity_end_uses_event_end_and_dismiss_at():
    result = await apns_liveactivity.send_live_activity_end(
        activity_push_token="abcdef0123",
        content_state={"status": "served"},
        dismiss_at=1_700_000_000,
    )

    assert result.success is True
    instance = _FakeAPNs.last_instance
    assert instance is not None
    aps = instance.sent[-1].message["aps"]
    assert aps["event"] == "end"
    assert aps["dismissal-date"] == 1_700_000_000
    assert aps["content-state"]["status"] == "served"


@pytest.mark.asyncio
async def test_send_live_activity_raises_on_410():
    instance = _FakeAPNs(key="x", key_id="x", team_id="x", topic="x", use_sandbox=True)
    instance.queue_response(_FakeResponse(status="410", description="Unregistered"))
    apns_liveactivity._apns_client = instance  # cache fake instance directly

    with pytest.raises(apns_liveactivity.APNsTokenExpiredError):
        await apns_liveactivity.send_live_activity_update(
            activity_push_token="zzz",
            content_state={"status": "preparing"},
        )


@pytest.mark.asyncio
async def test_send_live_activity_returns_failure_on_other_status():
    instance = _FakeAPNs(key="x", key_id="x", team_id="x", topic="x", use_sandbox=True)
    instance.queue_response(_FakeResponse(status="500", description="Internal"))
    apns_liveactivity._apns_client = instance

    result = await apns_liveactivity.send_live_activity_update(
        activity_push_token="zzz",
        content_state={"status": "preparing"},
    )
    assert result.success is False
    assert result.status_code == 500


@pytest.mark.asyncio
async def test_send_live_activity_raises_when_settings_missing(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APNS_KEY_ID", "")
    apns_liveactivity.reset_client_for_tests()

    with pytest.raises(apns_liveactivity.APNsConfigurationError):
        await apns_liveactivity.send_live_activity_update(
            activity_push_token="zzz",
            content_state={"status": "preparing"},
        )


@pytest.mark.asyncio
async def test_empty_token_raises_value_error():
    with pytest.raises(ValueError):
        await apns_liveactivity.send_live_activity_update(
            activity_push_token="",
            content_state={"status": "preparing"},
        )
