"""API URL routes."""

from __future__ import annotations

from django.urls import path

from . import sse, views

urlpatterns = [
    path("documents/", views.DocumentViewSet.as_view({"get": "list", "post": "create"})),
    path("documents/<uuid:pk>/", views.DocumentViewSet.as_view({"get": "retrieve", "delete": "destroy"})),
    path("documents/<uuid:pk>/content/", views.content_view),
    path("documents/<uuid:pk>/download/", views.download_view),
    path("documents/<uuid:pk>/events/", sse.sse_view),
    path("search/", views.search_view),
    path("config/", views.config_view),
    path("agent/tools/", views.agent_tools_view),
    path("agent/tools/call/", views.agent_tools_call_view),
]