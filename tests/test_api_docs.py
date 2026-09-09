"""HTTP documentation contracts and startup state regression coverage."""

import httpx
import pytest

from sense_every_zone.api import server
from sense_every_zone.registry import SensorRegistry, _ZoneConfig
from sense_every_zone.drivers.mock import MockSensor


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(server, "_registry", None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.parametrize("path,content_type,expected", [
    ("/agent-docs", "text/markdown", "# Sense Every Zone agent guide"),
    ("/agent-docs/api-reference", "text/markdown", "# Sense Every Zone API reference"),
    ("/llms.txt", "text/plain", "/openapi.json"),
])
async def test_docs_without_registry(client, path, content_type, expected):
    response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert expected in response.text


async def test_openapi_documents_content_types_and_errors(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    for path in ("/agent-docs", "/agent-docs/api-reference"):
        assert "text/markdown" in paths[path]["get"]["responses"]["200"]["content"]
    for code in ("404", "503"):
        assert "application/json" in paths["/zones/{zone_id}/status"]["get"]["responses"][code]["content"]


async def test_status_errors_and_health_without_registry(client, monkeypatch):
    assert (await client.get("/health")).json()["ok"] is False
    assert (await client.get("/zones")).json() == []
    response = await client.get("/zones/missing/status")
    assert response.status_code == 503
    assert response.json() == {"detail": "Registry not initialised"}
    monkeypatch.setattr(server, "_registry", SensorRegistry([]))
    assert (await client.get("/zones/missing/status")).status_code == 404


async def test_initial_zone_state_is_consistent(client, monkeypatch):
    sensor = MockSensor(sensor_id="mock", zone_id="test", config={})
    registry = SensorRegistry([_ZoneConfig("test", "Test", 5, [sensor])])
    monkeypatch.setattr(server, "_registry", registry)
    try:
        assert registry.latest("test").polled_at == 0
        assert (await client.get("/health")).json()["ok"] is False
        summary = (await client.get("/zones")).json()[0]
        assert summary["state"] == "unknown"
        assert summary["sensor_count"] == 1
        body = (await client.get("/zones/test/status")).json()
        assert body["equipment_status"] == "unknown"
        assert body["activity"] == "unknown"
        assert body["activity_since"] is None
    finally:
        registry.close()


async def test_discovery_respects_proxy_prefix():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app, root_path="/sensors"),
        base_url="http://test",
    ) as client:
        response = await client.get("/llms.txt")
    assert "(/sensors/agent-docs)" in response.text
    assert "(/sensors/openapi.json)" in response.text
