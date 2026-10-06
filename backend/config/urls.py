"""Root URL configuration."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.staticfiles.views import serve as staticfiles_serve
from django.urls import include, path, re_path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("documents.api.urls")),
]

# Serve Django static assets (admin CSS/JS). uvicorn does not serve static
# files like runserver does, so we wire it up explicitly. `insecure=True`
# makes the view serve from the staticfiles finders regardless of DEBUG,
# which also keeps the admin styled under pytest (DEBUG is forced off there).
urlpatterns.append(
    re_path(
        r"^static/(?P<path>.*)$",
        staticfiles_serve,
        kwargs={"insecure": True},
    )
)