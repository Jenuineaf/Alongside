"""Notifications views — UI preview from v5 mockups."""

from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def list_notifications(request):
    return render(request, "notifications/list.html", {"tab_active": "alerts", "unread_alerts": 3})
