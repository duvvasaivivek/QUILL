from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    """Render the initial application landing page."""
    return render(request, "core/home.html")


def health(request):
    """Expose a lightweight probe endpoint for hosting platforms."""
    return JsonResponse({"status": "ok", "service": "quill"})
