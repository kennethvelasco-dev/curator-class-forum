"""Views for class discussions."""

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import verified_required
from apps.channels.models import Channel
from apps.discussions.forms import ThreadCreateForm
from apps.discussions.models import Thread
from apps.servers.models import Server
from apps.servers.services.access import user_can_access_channel


@never_cache
@verified_required
@require_http_methods(["GET", "POST"])
def create_thread(request, server_id, channel_id):
    """Allow an authorized channel member to publish a new thread."""
    server = get_object_or_404(
        Server,
        pk=server_id,
        is_active=True,
    )

    channel = get_object_or_404(
        Channel,
        pk=channel_id,
        server=server,
    )

    if not request.user.is_active or not user_can_access_channel(
        request.user,
        channel,
    ):
        raise Http404

    if request.method == "POST":
        form = ThreadCreateForm(request.POST)

        if form.is_valid():
            Thread.objects.create(
                channel=channel,
                author=request.user,
                title=form.cleaned_data["title"],
                body=form.cleaned_data["body"],
                is_anonymous=form.cleaned_data["is_anonymous"],
            )

            return redirect(
                "channels:subject",
                server_id=server.pk,
                channel_id=channel.pk,
            )
    else:
        form = ThreadCreateForm()

    return render(
        request,
        "discussions/create_thread.html",
        {
            "server": server,
            "channel": channel,
            "form": form,
        },
    )