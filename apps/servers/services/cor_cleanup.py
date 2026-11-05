"""Retryable cleanup of CoR files after a request decision."""

import logging
from datetime import timedelta
from enum import Enum

from django.db import DatabaseError, connections, router, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.servers.models import (
    CorCleanupStatus,
    JoinRequest,
    RequestStatus,
    ServerRequest,
)
from apps.servers.storage import CorDeletionResult, delete_cor


logger = logging.getLogger(__name__)

COR_CLEANUP_CLAIM_TIMEOUT = timedelta(minutes=30)


class CorCleanupOutcome(Enum):
    SKIPPED_PENDING = "skipped_pending"
    FINALIZED_NO_REFERENCE = "finalized_no_reference"
    DELETED = "deleted"
    ALREADY_ABSENT = "already_absent"
    CLAIM_IN_PROGRESS = "claim_in_progress"
    STORAGE_FAILED_RETRYABLE = "storage_failed_retryable"
    FAILED_RETRYABLE = "storage_failed_retryable"
    ALREADY_COMPLETE = "already_complete"
    STALE = "stale"
    INELIGIBLE = "ineligible"
    REQUIRES_COMMITTED_TRANSACTION = "requires_committed_transaction"
    REQUEST_RETRIEVAL_FAILED = "request_retrieval_failed"
    ATTEMPT_RESERVATION_FAILED = "attempt_reservation_failed"
    STORAGE_FAILURE_RECORDING_FAILED = "storage_failure_recording_failed"
    COMPLETION_RECORDING_FAILED = "completion_recording_failed"
    FINALIZATION_RECORDING_FAILED = "finalization_recording_failed"
    PROCESSING_FAILED = "processing_failed"


_FINAL_STATUSES = (RequestStatus.APPROVED, RequestStatus.REJECTED)
_ELIGIBLE_CLEANUP_STATUSES = (
    CorCleanupStatus.NOT_REQUIRED,
    CorCleanupStatus.PENDING,
)


def _conditional_update(
    model,
    *,
    using,
    request_pk,
    status,
    cor_file,
    cleanup_status,
    claim_attempt=None,
):
    queryset = model._base_manager.using(using).filter(
        pk=request_pk,
        status=status,
        cor_file=cor_file,
        cor_cleanup_status=cleanup_status,
    )
    if claim_attempt is not None:
        queryset = queryset.filter(cor_cleanup_attempts=claim_attempt)
    return queryset


def _reserve_claim(model, *, using, current):
    reserved_at = timezone.now()
    stale_before = reserved_at - COR_CLEANUP_CLAIM_TIMEOUT
    eligible_state = (
        Q(cor_cleanup_status__in=_ELIGIBLE_CLEANUP_STATUSES)
        | Q(
            cor_cleanup_status=CorCleanupStatus.PROCESSING,
            cor_cleanup_last_attempt_at__lte=stale_before,
        )
        | Q(
            cor_cleanup_status=CorCleanupStatus.PROCESSING,
            cor_cleanup_last_attempt_at__isnull=True,
        )
    )
    try:
        with transaction.atomic(using=using):
            queryset = model._base_manager.using(using).filter(
                pk=current.pk,
                status=current.status,
                cor_file=current.cor_file,
            ).filter(eligible_state)
            reserved = queryset.update(
                cor_cleanup_status=CorCleanupStatus.PROCESSING,
                cor_cleanup_attempts=F("cor_cleanup_attempts") + 1,
                cor_cleanup_last_attempt_at=reserved_at,
                updated_at=reserved_at,
            )
            if reserved != 1:
                return None
            attempt = model._base_manager.using(using).values_list(
                "cor_cleanup_attempts",
                flat=True,
            ).get(pk=current.pk)
    except DatabaseError as error:
        logger.warning(
            "CoR cleanup attempt reservation failed for %s "
            "(exception type %s).",
            model.__name__,
            type(error).__name__,
        )
        return CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED
    return attempt


def _read_current(model, request_pk, using):
    return model._base_manager.using(using).get(pk=request_pk)


def _classify_current(model, request_pk, using):
    try:
        current = _read_current(model, request_pk, using)
    except model.DoesNotExist:
        return CorCleanupOutcome.STALE
    except DatabaseError as error:
        logger.warning(
            "CoR cleanup state could not be re-read for %s "
            "(exception type %s).",
            model.__name__,
            type(error).__name__,
        )
        return CorCleanupOutcome.REQUEST_RETRIEVAL_FAILED

    if current.status == RequestStatus.PENDING:
        return CorCleanupOutcome.SKIPPED_PENDING
    if current.status not in _FINAL_STATUSES:
        return CorCleanupOutcome.INELIGIBLE
    if current.cor_cleanup_status == CorCleanupStatus.COMPLETE:
        return CorCleanupOutcome.ALREADY_COMPLETE
    if current.cor_cleanup_status == CorCleanupStatus.PROCESSING:
        if (
            current.cor_cleanup_last_attempt_at is not None
            and current.cor_cleanup_last_attempt_at
            > timezone.now() - COR_CLEANUP_CLAIM_TIMEOUT
        ):
            return CorCleanupOutcome.CLAIM_IN_PROGRESS
    return CorCleanupOutcome.STALE


def _record_storage_failure(
    model,
    *,
    using,
    request_pk,
    status,
    cor_file,
    claim_attempt,
):
    try:
        updated = _conditional_update(
            model,
            using=using,
            request_pk=request_pk,
            status=status,
            cor_file=cor_file,
            cleanup_status=CorCleanupStatus.PROCESSING,
            claim_attempt=claim_attempt,
        ).update(
            cor_cleanup_status=CorCleanupStatus.PENDING,
            updated_at=timezone.now(),
        )
    except DatabaseError as error:
        logger.warning(
            "CoR storage failure state could not be recorded for %s "
            "(exception type %s).",
            model.__name__,
            type(error).__name__,
        )
        return CorCleanupOutcome.STORAGE_FAILURE_RECORDING_FAILED

    if updated != 1:
        return _classify_current(model, request_pk, using)
    return CorCleanupOutcome.STORAGE_FAILED_RETRYABLE


def attempt_cor_cleanup(request_obj, *, storage=None):
    """Reserve a durable attempt before storage, then CAS the verified result."""
    model = type(request_obj)
    if model not in (ServerRequest, JoinRequest):
        raise TypeError("CoR cleanup supports ServerRequest and JoinRequest.")

    using = request_obj._state.db or router.db_for_read(
        model,
        instance=request_obj,
    )
    if connections[using].in_atomic_block:
        return CorCleanupOutcome.REQUIRES_COMMITTED_TRANSACTION

    try:
        current = _read_current(model, request_obj.pk, using)
    except model.DoesNotExist:
        return CorCleanupOutcome.STALE
    except DatabaseError as error:
        logger.warning(
            "CoR cleanup request retrieval failed for %s "
            "(exception type %s).",
            model.__name__,
            type(error).__name__,
        )
        return CorCleanupOutcome.REQUEST_RETRIEVAL_FAILED

    if current.status == RequestStatus.PENDING:
        return CorCleanupOutcome.SKIPPED_PENDING
    if current.status not in _FINAL_STATUSES:
        return CorCleanupOutcome.INELIGIBLE
    if current.cor_cleanup_status == CorCleanupStatus.COMPLETE:
        return CorCleanupOutcome.ALREADY_COMPLETE
    if current.cor_cleanup_status == CorCleanupStatus.PROCESSING and (
        current.cor_cleanup_last_attempt_at is not None
        and current.cor_cleanup_last_attempt_at
        > timezone.now() - COR_CLEANUP_CLAIM_TIMEOUT
    ):
        return CorCleanupOutcome.CLAIM_IN_PROGRESS
    if current.cor_cleanup_status not in (
        *_ELIGIBLE_CLEANUP_STATUSES,
        CorCleanupStatus.PROCESSING,
    ):
        return CorCleanupOutcome.STALE

    if not current.cor_file:
        finalized_at = timezone.now()
        try:
            updated = _conditional_update(
                model,
                using=using,
                request_pk=current.pk,
                status=current.status,
                cor_file=current.cor_file,
                cleanup_status=current.cor_cleanup_status,
            ).update(
                cor_cleanup_status=CorCleanupStatus.COMPLETE,
                updated_at=finalized_at,
            )
        except DatabaseError as error:
            logger.warning(
                "CoR cleanup no-reference finalization failed for %s "
                "(exception type %s).",
                model.__name__,
                type(error).__name__,
            )
            return CorCleanupOutcome.FINALIZATION_RECORDING_FAILED
        if updated != 1:
            return _classify_current(model, current.pk, using)
        return CorCleanupOutcome.FINALIZED_NO_REFERENCE

    claim = _reserve_claim(model, using=using, current=current)
    if claim is None:
        return _classify_current(model, current.pk, using)
    if claim == CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED:
        return claim
    claim_attempt = claim

    try:
        result = delete_cor(current.cor_file, storage=storage)
    except Exception as error:
        logger.warning(
            "CoR storage operation failed for %s (exception type %s).",
            model.__name__,
            type(error).__name__,
        )
        return _record_storage_failure(
            model,
            using=using,
            request_pk=current.pk,
            status=current.status,
            cor_file=current.cor_file,
            claim_attempt=claim_attempt,
        )

    if result not in (
        CorDeletionResult.DELETED,
        CorDeletionResult.ALREADY_ABSENT,
    ):
        logger.warning(
            "CoR storage operation returned an unexpected result for %s.",
            model.__name__,
        )
        return _record_storage_failure(
            model,
            using=using,
            request_pk=current.pk,
            status=current.status,
            cor_file=current.cor_file,
            claim_attempt=claim_attempt,
        )

    try:
        updated = _conditional_update(
            model,
            using=using,
            request_pk=current.pk,
            status=current.status,
            cor_file=current.cor_file,
            cleanup_status=CorCleanupStatus.PROCESSING,
            claim_attempt=claim_attempt,
        ).update(
            cor_file=None,
            cor_cleanup_status=CorCleanupStatus.COMPLETE,
            updated_at=timezone.now(),
        )
    except DatabaseError as error:
        logger.warning(
            "CoR cleanup completion could not be recorded for %s "
            "(exception type %s).",
            model.__name__,
            type(error).__name__,
        )
        return CorCleanupOutcome.COMPLETION_RECORDING_FAILED

    if updated != 1:
        return _classify_current(model, current.pk, using)
    if result == CorDeletionResult.ALREADY_ABSENT:
        return CorCleanupOutcome.ALREADY_ABSENT
    return CorCleanupOutcome.DELETED
