"""Discovery views — UI previews from v5 mockups."""

from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def home(request):
    return render(request, "discovery/home.html", {"tab_active": "home"})


@require_GET
def explore(request):
    from django.shortcuts import redirect
    from django.urls import reverse

    return redirect(reverse("posts:feed"))


@require_GET
def search(request):
    return render(request, "discovery/search.html")


@require_GET
def onboarding(request, step=1):
    step = max(1, min(int(step), 3))
    return render(request, "discovery/onboarding.html", {"step": step})
