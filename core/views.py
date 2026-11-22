from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

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
