"""Django admin / static asset tests.

What it does:
    Guards the operational requirement that Django admin login page loads
    and its CSS is served even under uvicorn (which doesn't serve static
    files by default).

How it works:
    - GETs /admin/login/ and asserts 200 + "admin" in the HTML.
    - GETs /static/admin/css/base.css and asserts 200 + text/css, consuming
      streaming_content to close the file handle promptly (the suite runs
      with warnings-as-errors, so leaked files would fail).
"""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_admin_page_loads(api_client):
    # What: admin login page renders successfully.
    # How: GETs /admin/login/, asserts 200 and "admin" appears in HTML.
    resp = api_client.get("/admin/login/")
    assert resp.status_code == 200
    assert b"admin" in resp.content.lower()


@pytest.mark.django_db
def test_admin_static_assets_are_served(api_client):
    """uvicorn does not serve static files by default; the admin must still be
    styled, so /static/ is wired into the URL config."""
    # What: admin CSS is reachable via the Django static view.
    # How: GETs the base.css static URL, asserts 200 + css content-type and
    #   that the streamed body contains "body" (proving real CSS bytes).
    resp = api_client.get("/static/admin/css/base.css")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/css")
    # Consume the streamed body so the underlying file is closed immediately
    # rather than during a later GC (which trips the warning-as-error policy).
    assert b"body" in b"".join(resp.streaming_content)
