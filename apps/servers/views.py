"""Views for class servers."""

import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import admin_required, verified_required
from apps.servers.forms import ServerRequestForm
from apps.servers.models import RequestStatus, ServerRequest
from apps.servers.services.server_requests import create_server_request
from apps.servers.storage import delete_cor, get_cor_storage


logger = logging.getLogger(__name__)


def _render_server_request(request, form, *, status=200):
    return render(
        request,
        "servers/server_request_form.html",
        {"form": form},
        status=status,
    )


def _delete_failed_submission_upload(storage, file_name):
    try:
        delete_cor(file_name, storage=storage)
    except Exception as error:
        logger.error(
            "CoR cleanup after failed server-request submission failed "
            "(exception type %s).",
            type(error).__name__,
        )


@verified_required
@require_http_methods(["GET", "POST"])
def server_request(request):
    if request.method == "GET":
        return _render_server_request(request, ServerRequestForm())

    form = ServerRequestForm(request.POST, request.FILES)
    if not form.is_valid():
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


@admin_required
@require_http_methods(["GET"])
def server_request_cor(request, request_id):
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
    return response
