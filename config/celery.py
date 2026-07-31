"""Celery application.

The file lives in the Architect's package because it sits next to settings, but
the *wiring* (broker URLs, eager mode, the schedule) is DevOps's call — see
`docs/deployment.md` §4 and §11.

Production note: on Render's free tier there is no worker process, so
`CELERY_TASK_ALWAYS_EAGER=True` and tasks run inline in the request. The
architecture is unchanged; only the executor differs. Scheduled work arrives via
a GitHub Actions cron hitting a secured endpoint instead of Celery Beat.
"""

import logging
import os

from celery import Celery

logger = logging.getLogger(__name__)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("config")

# All Celery settings live in Django settings under a CELERY_ prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Finds tasks.py in every installed app.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):  # pragma: no cover
    """Smoke-test task — proves the worker is consuming from the broker.

    `celery -A config call config.celery.debug_task`, then check the worker log.
    Logs rather than prints so the output survives in production, where stdout
    from a task is not necessarily captured.
    """
    logger.info("debug_task received: %r", self.request)
