"""Django admin / static asset tests."""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_admin_page_loads(api_client):
    resp = api_client.get("/admin/login/")
    assert resp.status_code == 200
    assert b"admin" in resp.content.lower()


@pytest.mark.django_db
def test_admin_static_assets_are_served(api_client):
    """uvicorn does not serve static files by default; the admin must still be
    styled, so /static/ is wired into the URL config."""
    resp = api_client.get("/static/admin/css/base.css")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/css")
    # Consume the streamed body so the underlying file is closed immediately
    # rather than during a later GC (which trips the warning-as-error policy).
    assert b"body" in b"".join(resp.streaming_content)