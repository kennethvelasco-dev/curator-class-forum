from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("servers/", include("apps.servers.urls")),
    path("channels/", include("apps.channels.urls")),
    path("discussions/", include("apps.discussions.urls")),
    path("announcements/", include("apps.announcements.urls")),
    path("moderation/", include("apps.moderation.urls")),
]
