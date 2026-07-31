"""Alongside project package.

Deliberately named `config`, not `alongside` — `product-spec.md` §7 asks for a
generic package name so renaming the product is a UI change, not a refactor.

Importing the Celery app here is what makes `@shared_task` work anywhere in the
project, and what lets `celery -A config worker` find it (docker-compose.yml).
"""

from config.celery import app as celery_app

__all__ = ("celery_app",)
