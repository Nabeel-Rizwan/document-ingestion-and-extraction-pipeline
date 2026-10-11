# Base class for Django application configuration objects.
from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    # Default primary key type for models in this app without an explicit pk.
    default_auto_field = "django.db.models.BigAutoField"
    # Python path / label of the application.
    name = "documents"