#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

# Enable postponed evaluation of annotations (PEP 563) so type hints are strings.
from __future__ import annotations

# os is used to set environment variables for the Django process.
import os
# sys provides access to the command-line arguments passed to this script.
import sys


def main() -> None:
    # Point Django at the project's settings module unless one is already set.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        # Import the management entry point lazily so the ImportError below can be handled.
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # Re-raise with a clearer, actionable message, chaining the original error.
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # Dispatch the CLI command encoded in sys.argv (e.g. "runserver", "migrate").
    execute_from_command_line(sys.argv)


# Only run the CLI when this file is executed directly, not when imported.
if __name__ == "__main__":
    main()