from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import admin_required

from .forms import ThresholdForm
from .models import Setting


@admin_required
@require_http_methods(["GET", "POST"])
def threshold_settings(request):
    """Task 8 / FR-14: one threshold for all classrooms, default 20%. Admin only."""
    form = ThresholdForm(request.POST or None, instance=Setting.get())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Warning threshold saved.")
        return redirect("threshold_settings")
    return render(request, "form.html", {"title": "Absence warning threshold",
                                         "form": form, "cancel_url": "home"})
