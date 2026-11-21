
"""Views for class channels."""

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.decorators import verified_required
from apps.channels.forms import (
    SubjectChannelEditForm,
    SubjectChannelForm,
)
from apps.channels.models import Channel, ChannelType
from apps.servers.models import Server
from apps.servers.permissions import can_view_server_member_list
from apps.servers.services.access import user_can_access_channel



@never_cache
@verified_required
@require_GET
def rules_channel(request, server_id):
    """Display the Rules channel to an authorized server member."""
    server = get_object_or_404(
        Server,
        pk=server_id,
        is_active=True,
    )

    rules_channel = get_object_or_404(
        Channel,
        server=server,
        channel_type=ChannelType.RULES,
    )

    if not request.user.is_active or not user_can_access_channel(
        request.user,
        rules_channel,
    ):
        raise Http404

    return render(
        request,
        "channels/rules.html",
        {
            "server": server,
            "channel": rules_channel,
        },
    )

@never_cache
@verified_required
@require_GET
def subject_channel(request, server_id, channel_id):
    """Display an accessible subject channel and professor details."""
    server = get_object_or_404(
        Server,
        pk=server_id,
        is_active=True,
    )

    channel = get_object_or_404(
        Channel,
        pk=channel_id,
        server=server,
        channel_type=ChannelType.SUBJECT,
    )

    if not request.user.is_active or not user_can_access_channel(
        request.user,
        channel,
    ):
        raise Http404

    return render(
        request,
        "channels/subject.html",
        {
            "server": server,
            "channel": channel,
            "can_edit": can_view_server_member_list(request.user, server),
        },
    )


@never_cache
@verified_required
@require_http_methods(["GET", "POST"])
def create_subject_channel(request, server_id):
    """Allow an active President or Officer to create a subject channel."""
    server = get_object_or_404(
        Server,
        pk=server_id,
        is_active=True,
    )

    if not request.user.is_active or not can_view_server_member_list(
        request.user,
        server,
    ):
        raise Http404

    if request.method == "GET":
        form = SubjectChannelForm()
    else:
        form = SubjectChannelForm(request.POST)

        if form.is_valid():
            subject_code = form.cleaned_data["subject_code"]

            if Channel.objects.filter(
                server=server,
                slug=subject_code,
            ).exists():
                form.add_error(
                    "subject_code",
                    "A channel with this subject code already exists.",
                )
            else:
                try:
                    with transaction.atomic():
                        Channel.objects.create(
                            server=server,
                            name=form.cleaned_data["name"],
                            slug=subject_code,
                            channel_type=ChannelType.SUBJECT,
                            professor_name=form.cleaned_data["professor_name"],
                            professor_email=form.cleaned_data["professor_email"],
                            office_hours=form.cleaned_data["office_hours"],
                        )
                except IntegrityError:
                    form.add_error(
                        "subject_code",
                        "A channel with this subject code already exists.",
                    )
                else:
                    messages.success(
                        request,
                        "Subject channel created successfully.",
                    )
                    return redirect(
                        "channels:create_subject",
                        server_id=server.pk,
                    )

    return render(
        request,
        "channels/create_subject.html",
        {
            "server": server,
            "form": form,
        },
    )
@never_cache
@verified_required
@require_http_methods(["GET", "POST"])
def edit_subject_channel(request, server_id, channel_id):
    """Allow an active President or Officer to edit a subject channel."""
    server = get_object_or_404(
        Server,
        pk=server_id,
        is_active=True,
    )

    channel = get_object_or_404(
        Channel,
        pk=channel_id,
        server=server,
        channel_type=ChannelType.SUBJECT,
    )

    if not request.user.is_active or not can_view_server_member_list(
        request.user,
        server,
    ):
        raise Http404

    initial_data = {
        "name": channel.name,
        "professor_name": channel.professor_name,
        "professor_email": channel.professor_email,
        "office_hours": channel.office_hours,
    }

    if request.method == "POST":
        form = SubjectChannelEditForm(request.POST)

        if form.is_valid():
            channel.name = form.cleaned_data["name"]
            channel.professor_name = form.cleaned_data["professor_name"]
            channel.professor_email = form.cleaned_data["professor_email"]
            channel.office_hours = form.cleaned_data["office_hours"]
            channel.save(
                update_fields=[
                    "name",
                    "professor_name",
                    "professor_email",
                    "office_hours",
                ]
            )

            messages.success(
                request,
                "Subject channel updated successfully.",
            )

            return redirect(
                "channels:subject",
                server_id=server.pk,
                channel_id=channel.pk,
            )
    else:
        form = SubjectChannelEditForm(initial=initial_data)

    return render(
        request,
        "channels/edit_subject.html",
        {
            "server": server,
            "channel": channel,
            "form": form,
        },
    )
