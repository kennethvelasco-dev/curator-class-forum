"""Reusable access checks for authenticated account views."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render


def is_platform_admin(user):
    """Return True only for active platform staff accounts.

    Server membership roles (Student, Officer, President) never grant
    Platform Admin privileges; this predicate checks global user flags only.
    """
    return user.is_active and user.is_staff


def admin_required(view_func):
    """Restrict a view to active Platform Admins.

    Anonymous users are redirected to the Curator login page (next preserved).
    Authenticated users who are not active platform staff receive HTTP 403.
    """
    @login_required
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not is_platform_admin(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped_view


def verified_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_email_verified:
            return render(
                request,
                "accounts/verification_required.html",
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return wrapped_view
