import json
from pathlib import Path

import pytest

from instabotai.providers.private import PrivateInstagramProvider, PrivateInstagramProviderError
from instabotai.settings import Settings


class FakeResponse:
    status_code = 200
    url = "https://i.instagram.com/api/v1/accounts/current_user/?access_token=secret"
    request = type("Request", (), {"method": "GET"})()


class FakeClient:
    def __init__(self) -> None:
        self.device = None
        self.user_agent = None
        self.phone_number = None
        self.private = type("Private", (), {"headers": {}})()
        self.logged = []
        self.challenge_code_handler = None
        self.change_password_handler = None

    def set_device(self, device):
        self.device = device

    def set_user_agent(self, user_agent):
        self.user_agent = user_agent

    def request_log(self, response):
        self.logged.append(response.status_code)


def test_credential_file_requires_explicit_research_mode(tmp_path: Path) -> None:
    bundle = tmp_path / "credentials.json"
    bundle.write_text(json.dumps({"username": "owner", "password": "secret"}))
    provider = PrivateInstagramProvider(
        Settings(_env_file=None, private_credentials_file=str(bundle)),
        client=FakeClient(),
    )

    with pytest.raises(PrivateInstagramProviderError, match="RESEARCH_MODE"):
        provider._credential_bundle()


def test_research_client_accepts_device_headers_handlers_and_trace(tmp_path: Path) -> None:
    device = tmp_path / "device.json"
    headers = tmp_path / "headers.json"
    trace = tmp_path / "trace.jsonl"
    device.write_text(json.dumps({"manufacturer": "test", "model": "lab"}))
    headers.write_text(json.dumps({"X-Lab-Header": "enabled"}))

    settings = Settings(
        _env_file=None,
        private_research_mode=True,
        private_device_profile_file=str(device),
        private_headers_file=str(headers),
        private_user_agent="InstabotAI Authorized Lab",
        private_phone_number="+15555550123",
        private_challenge_code="123456",
        private_replacement_password="replacement-secret",
        private_request_trace_path=str(trace),
    )
    provider = PrivateInstagramProvider(settings, client=FakeClient())
    client = provider._client
    assert client is not None

    provider._configure_research_client(client, {})

    assert client.device == {"manufacturer": "test", "model": "lab"}
    assert client.user_agent == "InstabotAI Authorized Lab"
    assert client.private.headers["X-Lab-Header"] == "enabled"
    assert client.phone_number == "+15555550123"
    assert client.challenge_code_handler("owner", object()) == "123456"
    assert client.change_password_handler("owner") == "replacement-secret"

    client.request_log(FakeResponse())
    record = json.loads(trace.read_text().strip())
    assert record["status"] == 200
    assert "secret" not in record["url"]
    assert "[redacted]" in record["url"]
