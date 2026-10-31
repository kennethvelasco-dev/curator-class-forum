"""Reusable access checks for authenticated account views."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


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
