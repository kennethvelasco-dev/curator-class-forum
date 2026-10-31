"""Views for account pages and authentication."""

from django.shortcuts import redirect, render

from apps.accounts.forms import RegistrationForm


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("accounts:registration_complete")
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def registration_complete(request):
    return render(request, "accounts/registration_complete.html")
