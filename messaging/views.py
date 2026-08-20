"""Messaging views — UI previews from v5 mockups."""

from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def list_conversations(request):
    return render(request, "messaging/list.html", {"tab_active": "messages"})


@require_GET
def thread(request, pk):
    return render(request, "messaging/thread.html", {"conversation_id": pk})


@require_GET
def start(request, user_pk):
    return render(request, "messaging/thread.html", {"conversation_id": None, "user_pk": user_pk})
