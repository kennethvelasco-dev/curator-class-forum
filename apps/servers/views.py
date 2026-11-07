"""Views for class servers."""

import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.decorators import admin_required, verified_required
from apps.servers.forms import (
    ServerRequestDecisionForm,
    ServerRequestForm,
)
from apps.servers.models import (
    RequestStatus,
    SERVER_REQUEST_PENDING_MESSAGE,
    ServerRequest,
)
from apps.servers.services.server_requests import (
    create_server_request,
    decide_server_request,
)
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


def _delete_failed_submission_upload(storage, file_name):
    """Retry deletion once for the exact upload left by a failed submission."""
    for attempt in range(2):
        try:
            delete_cor(file_name, storage=storage)
            return True
        except Exception as error:
            if attempt == 1:
                logger.error(
                    "CoR cleanup after failed server-request submission "
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
