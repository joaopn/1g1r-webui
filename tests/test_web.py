from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r.web.app import create_app


@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as client:
        yield client


@pytest.mark.parametrize(
    "path", ["/", "/settings", "/section/conversion", "/section/matching", "/section/discarded"]
)
def test_pages_render_with_sidebar(client, path):
    response = client.get(path)
    assert response.status_code == HTTPStatus.OK
    for label in (
        "Home",
        "Conversion",
        "Matching &amp; 1G1R",
        "Discarded",
        "Settings",
        "+ Add platform",
    ):
        assert label in response.text


def test_unknown_section_is_404(client):
    assert client.get("/section/nope").status_code == HTTPStatus.NOT_FOUND


def test_footer_warns_without_source_url(client):
    assert "Source URL not configured" in client.get("/").text


def test_footer_links_source_when_configured(make_settings):
    app = create_app(make_settings({"app": {"source_url": "https://example.org/src"}}))
    with TestClient(app) as client:
        assert 'href="https://example.org/src"' in client.get("/").text


def test_settings_shows_effective_config(client):
    assert "page_size" in client.get("/settings").text


def test_healthz_reports_schema_version(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["schema_version"] >= 1


def test_static_assets_served(client):
    assert client.get("/static/app.css").status_code == HTTPStatus.OK
    assert client.get("/static/vendor/htmx.min.js").status_code == HTTPStatus.OK
