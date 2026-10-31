from django.urls import path

from apps.accounts import views

app_name = "accounts"
urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path(
        "registration/complete/",
        views.registration_complete,
        name="registration_complete",
    ),
    path(
        "verify/<int:user_id>/<str:token>/",
        views.verify_email,
        name="verify_email",
    ),
    path(
        "verify-registration/<int:registration_id>/<str:token>/",
        views.complete_registration,
        name="complete_registration",
    ),
]
