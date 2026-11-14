from django.urls import path

from . import views_settings

# BE2: add the attendance / report URLs to this list
urlpatterns = [
    path("threshold/", views_settings.threshold_settings, name="threshold_settings"),
]
