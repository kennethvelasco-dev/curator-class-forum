
"""URL patterns for class channels."""

from django.urls import path

from apps.channels import views

app_name = "channels"

urlpatterns = [
    path(
        "<int:server_id>/rules/",
        views.rules_channel,
        name="rules",
    ),
    path(
        "<int:server_id>/subjects/<int:channel_id>/",
        views.subject_channel,
        name="subject",
    ),
    path(
        "<int:server_id>/subjects/<int:channel_id>/edit/",
        views.edit_subject_channel,
        name="edit_subject",
    ),
    path(
        "<int:server_id>/subjects/create/",
        views.create_subject_channel,
        name="create_subject",
    ),

]
