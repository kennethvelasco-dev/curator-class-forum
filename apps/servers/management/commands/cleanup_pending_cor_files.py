"""Retry cleanup for approved or rejected requests with pending CoR files."""

import logging
from datetime import timedelta
from itertools import cycle

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.db.models import F, Q
from django.utils import timezone

from apps.servers.models import (
    CorCleanupStatus,
    JoinRequest,
    RequestStatus,
    ServerRequest,
)
from apps.servers.services.cor_cleanup import (
    COR_CLEANUP_CLAIM_TIMEOUT,
    CorCleanupOutcome,
    attempt_cor_cleanup,
)


logger = logging.getLogger(__name__)


_REQUEST_MODELS = (ServerRequest, JoinRequest)
_FINAL_STATUSES = (RequestStatus.APPROVED, RequestStatus.REJECTED)
_UNRESOLVED_OUTCOMES = {
    CorCleanupOutcome.STORAGE_FAILED_RETRYABLE,
    CorCleanupOutcome.STORAGE_FAILURE_RECORDING_FAILED,
    CorCleanupOutcome.REQUEST_RETRIEVAL_FAILED,
    CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED,
    CorCleanupOutcome.COMPLETION_RECORDING_FAILED,
    CorCleanupOutcome.FINALIZATION_RECORDING_FAILED,
    CorCleanupOutcome.REQUIRES_COMMITTED_TRANSACTION,
    CorCleanupOutcome.PROCESSING_FAILED,
}


def _eligible_requests(model):
    return model.objects.filter(
        status__in=_FINAL_STATUSES,
    ).filter(
        Q(cor_cleanup_status=CorCleanupStatus.PENDING)
        | Q(
            cor_cleanup_status=CorCleanupStatus.PROCESSING,
            cor_cleanup_last_attempt_at__lte=(
                timezone.now() - COR_CLEANUP_CLAIM_TIMEOUT
            ),
        )
        | Q(
            cor_cleanup_status=CorCleanupStatus.PROCESSING,
            cor_cleanup_last_attempt_at__isnull=True,
        )
    )


def _eligible_request_queues(model):
    eligible = _eligible_requests(model)
    previously_attempted = eligible.filter(
        cor_cleanup_last_attempt_at__isnull=False,
    ).order_by(
        F("cor_cleanup_last_attempt_at").asc(),
        "created_at",
        "pk",
    )
    never_attempted = eligible.filter(
        cor_cleanup_last_attempt_at__isnull=True,
    ).order_by("created_at", "pk")
    return previously_attempted, never_attempted


def _retrieve_request(model, request_pk):
    return model._base_manager.get(pk=request_pk)


def _most_recent_attempted_model():
    latest = []
    for model in _REQUEST_MODELS:
        attempt = (
            model.objects.filter(cor_cleanup_last_attempt_at__isnull=False)
            .order_by("-cor_cleanup_last_attempt_at", "-pk")
            .values_list("cor_cleanup_last_attempt_at", flat=True)
            .first()
        )
        if attempt is not None:
            latest.append((attempt, model))

    if not latest:
        return None
    return max(latest, key=lambda entry: (entry[0], entry[1] is ServerRequest))[1]


def _selected_requests(limit):
    most_recent = _most_recent_attempted_model()
    first_model = (
        JoinRequest if most_recent is ServerRequest else ServerRequest
    )
    model_order = (
        (first_model, JoinRequest if first_model is ServerRequest else ServerRequest)
    )
    selected = []
    queues = {
        model: _eligible_request_queues(model)
        for model in model_order
    }

    for queue_index in (0, 1):
        iterators = {
            model: iter(
                queues[model][queue_index].values_list("pk", flat=True)
            )
            for model in model_order
        }
        remaining = set(model_order)
        turn_order = cycle(model_order)

        while remaining and (limit is None or len(selected) < limit):
            model = next(turn_order)
            if model not in remaining:
                continue
            try:
                request_pk = next(iterators[model])
            except StopIteration:
                remaining.remove(model)
                continue
            selected.append((model, request_pk))

        if limit is not None and len(selected) >= limit:
            break

    return selected


class Command(BaseCommand):
    help = (
        "Retry cleanup of approved or rejected requests' private CoR files. "
        "Previously attempted eligible requests are prioritized."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show eligible aggregate counts without checking file existence.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of requests to process across both models.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be a positive integer.")

        try:
            per_model_counts = {
                model: _eligible_requests(model).count()
                for model in _REQUEST_MODELS
            }
            if options["dry_run"]:
                eligible_count = sum(per_model_counts.values())
                self.stdout.write(
                    "Dry run: "
                    f"eligible={eligible_count} "
                    f"server_requests={per_model_counts[ServerRequest]} "
                    f"join_requests={per_model_counts[JoinRequest]} "
                    "files_checked=0; "
                    "dry-run does not verify individual file existence."
                )
                return

            selected = _selected_requests(limit)
        except Exception as error:
            logger.error(
                "CoR cleanup batch selection failed (exception type %s).",
                type(error).__name__,
            )
            raise CommandError(
                "CoR cleanup could not query eligible requests."
            ) from error

        outcome_counts = {outcome: 0 for outcome in CorCleanupOutcome}

        for model, request_pk in selected:
            try:
                request_obj = _retrieve_request(model, request_pk)
            except ObjectDoesNotExist:
                outcome = CorCleanupOutcome.STALE
            except DatabaseError as error:
                logger.warning(
                    "CoR cleanup request retrieval failed for %s "
                    "(exception type %s).",
                    model.__name__,
                    type(error).__name__,
                )
                outcome = CorCleanupOutcome.REQUEST_RETRIEVAL_FAILED
            except Exception as error:
                logger.warning(
                    "CoR cleanup request processing failed for %s "
                    "(exception type %s).",
                    model.__name__,
                    type(error).__name__,
                )
                outcome = CorCleanupOutcome.PROCESSING_FAILED
            else:
                try:
                    outcome = attempt_cor_cleanup(request_obj)
                except Exception as error:
                    logger.warning(
                        "CoR cleanup processing failed for %s "
                        "(exception type %s).",
                        model.__name__,
                        type(error).__name__,
                    )
                    outcome = CorCleanupOutcome.PROCESSING_FAILED

            outcome_counts[outcome] += 1

        unresolved_failures = sum(
            outcome_counts[outcome] for outcome in _UNRESOLVED_OUTCOMES
        )
        ordered_counts = (
            ("deleted", CorCleanupOutcome.DELETED),
            ("already_absent", CorCleanupOutcome.ALREADY_ABSENT),
            ("finalized_no_reference", CorCleanupOutcome.FINALIZED_NO_REFERENCE),
            ("storage_failed_retryable", CorCleanupOutcome.STORAGE_FAILED_RETRYABLE),
            (
                "storage_failure_recording_failed",
                CorCleanupOutcome.STORAGE_FAILURE_RECORDING_FAILED,
            ),
            ("request_retrieval_failed", CorCleanupOutcome.REQUEST_RETRIEVAL_FAILED),
            ("attempt_reservation_failed", CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED),
            ("completion_recording_failed", CorCleanupOutcome.COMPLETION_RECORDING_FAILED),
            ("finalization_recording_failed", CorCleanupOutcome.FINALIZATION_RECORDING_FAILED),
            (
                "requires_committed_transaction",
                CorCleanupOutcome.REQUIRES_COMMITTED_TRANSACTION,
            ),
            ("processing_failed", CorCleanupOutcome.PROCESSING_FAILED),
            ("already_complete", CorCleanupOutcome.ALREADY_COMPLETE),
            ("claim_in_progress", CorCleanupOutcome.CLAIM_IN_PROGRESS),
            ("skipped_pending", CorCleanupOutcome.SKIPPED_PENDING),
            ("stale", CorCleanupOutcome.STALE),
            ("ineligible", CorCleanupOutcome.INELIGIBLE),
        )
        summary = " ".join(
            f"{name}={outcome_counts[outcome]}"
            for name, outcome in ordered_counts
        )
        self.stdout.write(
            f"CoR cleanup: selected={len(selected)} {summary} "
            f"unresolved_failures={unresolved_failures}"
        )
        if unresolved_failures:
            raise CommandError(
                f"{unresolved_failures} CoR cleanup failure(s) require attention."
            )
