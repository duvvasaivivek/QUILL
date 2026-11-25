from django.contrib.auth.views import LoginView
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from reports.views import access


class QuillLoginView(LoginView):
    def get_default_redirect_url(self):
        permissions = access(self.request)
        if permissions["can_view_dashboard"]:
            return reverse("owner_dashboard")
        if permissions["can_view_reports"]:
            return reverse("reports")
        if self.request.user.has_perm("sales.add_salesorder"):
            return super().get_default_redirect_url()
        return reverse("home")


def home(request):
    """Render the initial application landing page."""
    return render(request, "core/home.html")


def health(request):
    """Expose a lightweight probe endpoint for hosting platforms."""
    return JsonResponse({"status": "ok", "service": "quill"})


@require_safe
def manifest(request):
    return JsonResponse({
        "id": "/", "name": "QUILL Inventory and Sales", "short_name": "QUILL",
        "start_url": reverse("home"), "scope": "/", "display": "standalone",
        "background_color": "#ffffff", "theme_color": "#0d6efd",
        "icons": [
            {"src": staticfiles_storage.url(f"icons/quill-{size}.png"),
             "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any"}
            for size in (192, 512)
        ],
    }, content_type="application/manifest+json")


@require_safe
@never_cache
def service_worker(request):
    return render(request, "core/service-worker.js", content_type="application/javascript")
