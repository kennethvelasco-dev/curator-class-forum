"""Views for class servers."""

import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from apps.accounts.decorators import admin_required, verified_required
from apps.servers.context import set_active_server
from apps.servers.forms import (
    JoinRequestDecisionForm,
    JoinRequestForm,
    MembershipRoleChangeForm,
    PresidentTransferForm,
    ServerRequestDecisionForm,
    ServerRequestForm,
    ServerSwitchForm,
)
from apps.servers.models import (
    JoinRequest,
    Membership,
    MembershipRole,
    MembershipStatus,
    RequestStatus,
    SERVER_REQUEST_PENDING_MESSAGE,
    Server,
    ServerRequest,
)
from apps.servers.permissions import (
    can_view_server_member_list,
    is_active_president_of_server,
)
from apps.servers.services.server_requests import (
    create_join_request,
    create_server_request,
    decide_join_request,
    decide_server_request,
)
from apps.servers.services.roles import change_member_role
from apps.servers.services.transfer import transfer_presidency
from apps.servers.storage import delete_cor, get_cor_storage


logger = logging.getLogger(__name__)


def _render_server_request(request, form, *, status=200):
    """Render the server-request form with the supplied validation state."""
    return render(
        request,
        "servers/server_request_form.html",
        {"form": form},
        status=status,
    )


def _render_join_request(request, form, *, status=200):
    """Render the join-request form with the supplied validation state."""
    return render(
        request,
        "servers/join_request_form.html",
        {"form": form},
        status=status,
    )


def _delete_failed_submission_upload(storage, file_name):
    """Retry deletion once for the exact upload left by a failed submission."""
    for attempt in range(2):
        try:
            delete_cor(file_name, storage=storage)
            return True
        except Exception as error:
            if attempt == 1:
                logger.error(
                    "CoR cleanup after failed request submission "
                    "failed after retry (exception type %s).",
                    type(error).__name__,
                )
    return False


@verified_required
@require_http_methods(["GET", "POST"])
def server_request(request):
    """Accept a verified student's private CoR-backed server request."""
    if request.method == "GET":
        return _render_server_request(request, ServerRequestForm())

    form = ServerRequestForm(request.POST, request.FILES)
    if not form.is_valid():
        return _render_server_request(request, form)

    if ServerRequest.objects.filter(
        requester=request.user,
        status=RequestStatus.PENDING,
    ).exists():
        form.add_error(None, SERVER_REQUEST_PENDING_MESSAGE)
        return _render_server_request(request, form)

    uploaded_file = form.cleaned_data["cor_file"]
    try:
        storage = get_cor_storage()
        stored_file = storage.save(uploaded_file.name, uploaded_file)
    except Exception as error:
        logger.error(
            "Private CoR storage failed during server-request submission "
            "(exception type %s).",
            type(error).__name__,
        )
        form.add_error(
            "cor_file",
            "We could not securely store your document. Please try again.",
        )
        return _render_server_request(request, form, status=503)

    try:
        create_server_request(
            requester=request.user,
            proposed_name=form.cleaned_data["proposed_name"],
            proposed_section=form.cleaned_data["proposed_section"],
            cor_file=stored_file,
        )
    except ValidationError as error:
        _delete_failed_submission_upload(storage, stored_file)
        form.add_error(None, error.messages)
        return _render_server_request(request, form)
    except DatabaseError as error:
        _delete_failed_submission_upload(storage, stored_file)
        logger.error(
            "Server-request persistence failed (exception type %s).",
            type(error).__name__,
        )
        form.add_error(
            None,
            "We could not submit your request. Please try again.",
        )
        return _render_server_request(request, form, status=503)
    except Exception as error:
        _delete_failed_submission_upload(storage, stored_file)
        logger.error(
            "Server-request submission failed (exception type %s).",
            type(error).__name__,
        )
        form.add_error(
            None,
            "We could not submit your request. Please try again.",
        )
        return _render_server_request(request, form, status=503)

    messages.success(
        request,
        "Your server request was submitted and is pending Admin review.",
    )
    return redirect("servers:server_request")


@verified_required
@require_http_methods(["GET", "POST"])
def join_request(request):
    """Accept a verified student's private CoR-backed join request."""
    if request.method == "GET":
        return _render_join_request(request, JoinRequestForm(request=request))

    form = JoinRequestForm(request.POST, request.FILES, request=request)
    if not form.is_valid():
        return _render_join_request(request, form)

    server = form.cleaned_data["server"]
    if Membership.objects.filter(
        user=request.user,
        server=server,
        status=MembershipStatus.ACTIVE,
    ).exists():
        form.add_error("server", "You already belong to this server.")
        return _render_join_request(request, form)

    if JoinRequest.objects.filter(
        user=request.user,
        server=server,
        status=RequestStatus.PENDING,
    ).exists():
        form.add_error("server", "You already have a pending join request for this server.")
        return _render_join_request(request, form)

    uploaded_file = form.cleaned_data["cor_file"]
    try:
        storage = get_cor_storage()
        stored_file = storage.save(uploaded_file.name, uploaded_file)
    except Exception as error:
        logger.error(
            "Private CoR storage failed during join-request submission "
            "(exception type %s).",
            type(error).__name__,
        )
        form.add_error(
            "cor_file",
            "We could not securely store your document. Please try again.",
        )
        return _render_join_request(request, form, status=503)

    try:
        create_join_request(
            user=request.user,
            server=server,
            student_number=form.cleaned_data["student_number"],
            subjects=form.cleaned_data["subject_entries"],
            cor_file=stored_file,
        )
    except ValidationError as error:
        _delete_failed_submission_upload(storage, stored_file)
        form.add_error(None, error.messages)
        return _render_join_request(request, form)
    except DatabaseError as error:
        _delete_failed_submission_upload(storage, stored_file)
        logger.error(
            "Join-request persistence failed (exception type %s).",
            type(error).__name__,
        )
        form.add_error(
            None,
            "We could not submit your request. Please try again.",
        )
        return _render_join_request(request, form, status=503)
    except Exception as error:
        _delete_failed_submission_upload(storage, stored_file)
        logger.error(
            "Join-request submission failed (exception type %s).",
            type(error).__name__,
        )
        form.add_error(
            None,
            "We could not submit your request. Please try again.",
        )
        return _render_join_request(request, form, status=503)

    messages.success(
        request,
        "Your join request has been submitted successfully and is pending President review.",
    )
    return redirect("servers:join_request")


@never_cache
@verified_required
@require_http_methods(["GET"])
def join_request_queue(request):
    """Show the pending join requests for the acting President's server(s)."""
    president_memberships = Membership.objects.filter(
        user=request.user,
        role=MembershipRole.PRESIDENT,
        status=MembershipStatus.ACTIVE,
    ).select_related("server")
    if not president_memberships.exists():
        return render(
            request,
            "servers/join_request_queue.html",
            {"review_items": []},
            status=403,
        )

    server_ids = [membership.server_id for membership in president_memberships]
    pending_requests = list(
        JoinRequest.objects.filter(
            server_id__in=server_ids,
            status=RequestStatus.PENDING,
        )
        .select_related("user", "server")
        .order_by("created_at", "pk")
    )
    return render(
        request,
        "servers/join_request_queue.html",
        {"review_items": pending_requests},
    )


@never_cache
@verified_required
@require_POST
def decide_join_request_view(request, request_id):
    """Record a pending join-request decision from the active President."""
    form = JoinRequestDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            "; ".join(error for errors in form.errors.values() for error in errors),
        )
        return redirect("servers:join_request_queue")

    try:
        decided_request = decide_join_request(
            request_id=request_id,
            reviewer=request.user,
            decision=form.cleaned_data["decision"],
            decision_reason=form.cleaned_data["decision_reason"],
            membership_role=form.cleaned_data.get("membership_role"),
        )
    except JoinRequest.DoesNotExist:
        raise Http404 from None
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect("servers:join_request_queue")
    except DatabaseError as error:
        logger.error(
            "Join-request decision failed (exception type %s).",
            type(error).__name__,
        )
        messages.error(
            request,
            "We could not record this decision. Please try again.",
        )
        return redirect("servers:join_request_queue")

    if decided_request.status == RequestStatus.APPROVED:
        messages.success(request, "The join request was approved.")
    else:
        messages.success(request, "The join request was rejected.")
    return redirect("servers:join_request_queue")


@verified_required
@require_http_methods(["GET"])
def join_request_cor(request, request_id):
    """Serve a pending join request's CoR to its active President."""
    request_obj = get_object_or_404(
        JoinRequest,
        pk=request_id,
        status=RequestStatus.PENDING,
    )
    if not is_active_president_of_server(request.user, request_obj.server):
        raise Http404
    if not request_obj.cor_file:
        raise Http404

    try:
        document = get_cor_storage().open(request_obj.cor_file, "rb")
    except FileNotFoundError:
        raise Http404 from None
    except Exception as error:
        logger.error(
            "Private join-request CoR access failed (exception type %s).",
            type(error).__name__,
        )
        return HttpResponse(
            "We could not retrieve this document. Please try again later.",
            status=503,
        )

    return FileResponse(
        document,
        as_attachment=True,
        filename="join-request-cor.pdf",
        headers={
            "Cache-Control": "private, no-store",
        },
    )


def _render_admin_server_request_queue(
    request,
    *,
    form=None,
    decision_request_id=None,
    status=200,
):
    server_requests = list(
        ServerRequest.objects.filter(status=RequestStatus.PENDING)
        .select_related("requester")
        .order_by("created_at", "pk")
    )
    review_items = [
        {
            "server_request": server_request,
            "form": (
                form
                if server_request.pk == decision_request_id and form is not None
                else ServerRequestDecisionForm(
                    prefix=f"request-{server_request.pk}"
                )
            ),
        }
        for server_request in server_requests
    ]
    return render(
        request,
        "servers/admin_server_request_queue.html",
        {
            "review_items": review_items,
        },
        status=status,
    )


@never_cache
@admin_required
@require_http_methods(["GET"])
def admin_server_request_queue(request):
    """Show pending server requests to active platform staff."""
    return _render_admin_server_request_queue(request)


@never_cache
@admin_required
@require_POST
def decide_server_request_view(request, request_id):
    """Record an Admin decision for a pending server request."""
    form = ServerRequestDecisionForm(
        request.POST,
        prefix=f"request-{request_id}",
    )
    if not form.is_valid():
        return _render_admin_server_request_queue(
            request,
            form=form,
            decision_request_id=request_id,
            status=400,
        )

    try:
        decided_request = decide_server_request(
            request_id=request_id,
            reviewer=request.user,
            decision=form.cleaned_data["decision"],
            decision_reason=form.cleaned_data["decision_reason"],
        )
    except ServerRequest.DoesNotExist:
        raise Http404 from None
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect("servers:admin_server_request_queue")
    except DatabaseError as error:
        logger.error(
            "Server-request decision failed "
            "(exception type %s).",
            type(error).__name__,
        )
        messages.error(
            request,
            "We could not record this decision. Please try again.",
        )
        return redirect("servers:admin_server_request_queue")

    if decided_request.status == RequestStatus.APPROVED:
        messages.success(
            request,
            "The server request was approved and the class server was created.",
        )
    else:
        messages.success(request, "The server request was rejected.")
    return redirect("servers:admin_server_request_queue")


@admin_required
@require_http_methods(["GET"])
def server_request_cor(request, request_id):
    """Serve a pending request's CoR only to active platform staff."""
    request_obj = get_object_or_404(
        ServerRequest,
        pk=request_id,
        status=RequestStatus.PENDING,
    )
    if not request_obj.cor_file:
        raise Http404

    try:
        document = get_cor_storage().open(request_obj.cor_file, "rb")
    except FileNotFoundError:
        raise Http404 from None
    except Exception as error:
        logger.error(
            "Private CoR access failed (exception type %s).",
            type(error).__name__,
        )
        return HttpResponse(
            "We could not retrieve this document. Please try again later.",
            status=503,
        )

    response = FileResponse(document, content_type="application/pdf")
    response["Content-Disposition"] = (
        'inline; filename="server-request-cor.pdf"'
    )
    response["Cache-Control"] = "private, no-store"
    return response


@verified_required
@require_POST
def switch_server(request):
    """Switch the user's active server context after membership validation."""
    form = ServerSwitchForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Select a valid server.")
        return redirect("accounts:dashboard")

    if set_active_server(request, form.cleaned_data["server_id"]):
        messages.success(request, "Server context updated.")
    else:
        messages.error(
            request,
            "You do not have an active membership in that server.",
        )
    return redirect("accounts:dashboard")


@never_cache
@verified_required
@require_GET
def server_member_list(request, server_id):
    """Show active server members to its active President or Officers."""
    server = get_object_or_404(Server, pk=server_id, is_active=True)
    if not request.user.is_active or not can_view_server_member_list(
        request.user,
        server,
    ):
        raise Http404

    memberships = (
        Membership.objects.filter(
            server=server,
            status=MembershipStatus.ACTIVE,
        )
        .select_related("user")
        .order_by("user__full_name", "pk")
    )
    can_manage_roles = is_active_president_of_server(request.user, server)
    member_rows = [
        {
            "membership": membership,
            "role_form": MembershipRoleChangeForm(
                initial={
                    "new_role": membership.role,
                    "expected_role": membership.role,
                }
            ),
            "can_change_role": (
                can_manage_roles
                and membership.user_id != request.user.pk
                and membership.role
                in (MembershipRole.STUDENT, MembershipRole.OFFICER)
                and membership.user.is_active
                and membership.user.is_email_verified
            ),
        }
        for membership in memberships
    ]
    return render(
        request,
        "servers/member_list.html",
        {
            "server": server,
            "member_rows": member_rows,
        },
    )


@never_cache
@verified_required
@require_POST
def change_member_role_view(request, server_id, membership_id):
    """Change one member's role after server-scoped President authorization."""
    server = get_object_or_404(Server, pk=server_id, is_active=True)
    if (
        not request.user.is_active
        or not is_active_president_of_server(request.user, server)
    ):
        raise Http404

    form = MembershipRoleChangeForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "servers/member_role_change_error.html",
            {"server": server, "form": form},
            status=400,
        )
    expected_role = form.cleaned_data.get("expected_role") or None
    try:
        _, changed = change_member_role(
            server=server,
            acting_user=request.user,
            target_membership_id=membership_id,
            new_role=form.cleaned_data["new_role"],
            expected_role=expected_role,
        )
    except ValidationError as error:
        if hasattr(error, "message_dict"):
            for field, errors in error.message_dict.items():
                if field in form.fields:
                    for message in errors:
                        form.add_error(field, message)
                else:
                    form.add_error(None, errors)
        else:
            form.add_error(None, error.messages)
        return render(
            request,
            "servers/member_role_change_error.html",
            {"server": server, "form": form},
            status=400,
        )
    except DatabaseError as error:
        logger.error(
            "Member role change failed (exception type %s).",
            type(error).__name__,
        )
        form.add_error(
            None,
            "We could not update this member's role. Please try again.",
        )
        return render(
            request,
            "servers/member_role_change_error.html",
            {"server": server, "form": form},
            status=503,
        )

    if changed:
        messages.success(request, "The member's role was updated.")
    else:
        messages.info(request, "The member already has that role.")
    return redirect("servers:server_member_list", server_id=server.pk)


@never_cache
@verified_required
@require_http_methods(["GET", "POST"])
def transfer_presidency_view(request, server_id):
    """Allow the active President to transfer title to another active member."""
    server = get_object_or_404(Server, pk=server_id, is_active=True)
    if not is_active_president_of_server(request.user, server):
        raise Http404

    eligible = (
        Membership.objects.filter(
            server=server,
            status=MembershipStatus.ACTIVE,
            user__is_email_verified=True,
            user__is_active=True,
        )
        .exclude(user=request.user)
        .select_related("user")
        .order_by("user__full_name", "pk")
    )

    if request.method == "GET":
        form = PresidentTransferForm()
        return render(
            request,
            "servers/transfer_presidency.html",
            {
                "server": server,
                "form": form,
                "eligible_members": eligible,
            },
        )

    form = PresidentTransferForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "servers/transfer_presidency.html",
            {
                "server": server,
                "form": form,
                "eligible_members": eligible,
            },
            status=400,
        )

    try:
        transfer_presidency(
            server=server,
            acting_user=request.user,
            target_membership_id=form.cleaned_data["target_membership_id"],
            password=form.cleaned_data["password"],
        )
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return render(
            request,
            "servers/transfer_presidency.html",
            {
                "server": server,
                "form": form,
                "eligible_members": eligible,
            },
            status=400,
        )
    except DatabaseError as error:
        logger.error(
            "President transfer failed (exception type %s).",
            type(error).__name__,
        )
        messages.error(
            request,
            "We could not complete the transfer. Please try again.",
        )
        return redirect("accounts:dashboard")

    messages.success(
        request,
        "President title transferred successfully. You are now a student in this server.",
    )
    return redirect("accounts:dashboard")
