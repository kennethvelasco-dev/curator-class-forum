
"""Views for class channels."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Prefetch
from django.db.models.functions import Coalesce
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
from apps.discussions.models import Reply
from apps.servers.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Server,
)
from apps.servers.permissions import can_view_server_member_list
from apps.servers.services.access import user_can_access_channel


def _lock_channel_management_access(user, server_id):
    """Revalidate channel-management access using the role-change lock order."""
    server = Server.objects.select_for_update().filter(pk=server_id).first()
    if server is None or not server.is_active:
        raise Http404

    user_state = (
        get_user_model()._default_manager.filter(pk=user.pk)
        .values("is_active", "is_email_verified")
        .first()
    )
    if (
        user_state is None
        or not user_state["is_active"]
        or not user_state["is_email_verified"]
    ):
        raise Http404

    membership = (
        Membership.objects.select_for_update()
        .filter(
            user_id=user.pk,
            server=server,
            status=MembershipStatus.ACTIVE,
            role__in=(MembershipRole.PRESIDENT, MembershipRole.OFFICER),
        )
        .first()
    )
    if membership is None:
        raise Http404

    return server



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
    threads = (
        channel.threads.select_related("author")
        .annotate(
            reply_count=Count("replies"),
            last_activity=Coalesce(
                Max("replies__created_at"),
                F("created_at"),
            ),
        )
        .order_by("-last_activity", "-pk")
        .prefetch_related(
            Prefetch(
                "replies",
                queryset=Reply.objects.select_related("author").order_by(
                    "created_at",
                    "pk",
                ),
            )
        )
    )
    page_obj = Paginator(threads, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "channels/subject.html",
        {
            "server": server,
            "channel": channel,
            "can_edit": can_view_server_member_list(request.user, server),
            "threads": page_obj.object_list,
            "page_obj": page_obj,
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
            try:
                with transaction.atomic():
                    server = _lock_channel_management_access(
                        request.user,
                        server_id,
                    )
                    if Channel.objects.filter(
                        server=server,
                        slug=subject_code,
                    ).exists():
                        form.add_error(
                            "subject_code",
                            "A channel with this subject code already exists.",
                        )
                    else:
                        Channel.objects.create(
                            server=server,
                            name=form.cleaned_data["name"],
                            slug=subject_code,
                            subject_code=subject_code,
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
                if not form.errors:
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
        "edit_version": channel.edit_version,
        "name": channel.name,
        "professor_name": channel.professor_name,
        "professor_email": channel.professor_email,
        "office_hours": channel.office_hours,
    }

    if request.method == "POST":
        form = SubjectChannelEditForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                server = _lock_channel_management_access(
                    request.user,
                    server_id,
                )
                channel = get_object_or_404(
                    Channel.objects.select_for_update(),
                    pk=channel_id,
                    server=server,
                    channel_type=ChannelType.SUBJECT,
                )
                if channel.edit_version != form.cleaned_data["edit_version"]:
                    form.add_error(
                        None,
                        "Another officer has updated this channel. "
                        "Reload this page before saving your changes.",
                    )
                else:
                    channel.name = form.cleaned_data["name"]
                    channel.professor_name = form.cleaned_data["professor_name"]
                    channel.professor_email = form.cleaned_data["professor_email"]
                    channel.office_hours = form.cleaned_data["office_hours"]
                    channel.edit_version += 1
                    channel.save(
                        update_fields=[
                            "name",
                            "professor_name",
                            "professor_email",
                            "office_hours",
                            "edit_version",
                        ]
                    )

                if not form.errors:
                    messages.success(
                        request,
                        "Subject channel updated successfully.",
                     )

                    return redirect(
                        "channels:edit_subject",
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
