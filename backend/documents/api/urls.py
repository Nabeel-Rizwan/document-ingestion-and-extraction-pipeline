"""API URL routes."""

# Enable postponed evaluation of annotations (PEP 563).
from __future__ import annotations

# path() declares static/parameterized URL patterns.
from django.urls import path

# Import the SSE view module and the REST view module.
from . import sse, views

urlpatterns = [
    # Collection endpoint: GET lists documents, POST creates (uploads) one.
    path("documents/", views.DocumentViewSet.as_view({"get": "list", "post": "create"})),
    # Detail endpoint: GET retrieves one document, DELETE destroys it (UUID pk).
    path("documents/<uuid:pk>/", views.DocumentViewSet.as_view({"get": "retrieve", "delete": "destroy"})),
    # Extracted content of a document, optionally filtered/format-converted.
    path("documents/<uuid:pk>/content/", views.content_view),
    # Serves the original uploaded file as a download.
    path("documents/<uuid:pk>/download/", views.download_view),
    # Server-Sent Events stream of processing progress for a document.
    path("documents/<uuid:pk>/events/", sse.sse_view),
    # Full-text search over extracted blocks.
    path("search/", views.search_view),
    # Runtime configuration/limits for clients.
    path("config/", views.config_view),
    # Lists the agent tools available for invocation.
    path("agent/tools/", views.agent_tools_view),
    # Invokes a named agent tool with arguments.
    path("agent/tools/call/", views.agent_tools_call_view),
]