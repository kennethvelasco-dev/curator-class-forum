"""Models for class servers."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class RequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class MembershipRole(models.TextChoices):
    STUDENT = "student", "Student"
    OFFICER = "officer", "Officer"
    PRESIDENT = "president", "President"


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    LEFT = "left", "Left"
    REMOVED = "removed", "Removed"


class Server(models.Model):
    name = models.CharField(max_length=255)
    section = models.CharField(max_length=64, blank=True, default="")
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="servers_created",
    )

    def __str__(self):
        return self.name


class ServerRequest(models.Model):
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="server_requests",
    )
    proposed_name = models.CharField(max_length=255)
    proposed_section = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=RequestStatus,
        default=RequestStatus.PENDING,
    )
    cor_file = models.CharField(max_length=255, null=True, blank=True)
    decision_reason = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="server_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_server = models.OneToOneField(
        Server,
        on_delete=models.SET_NULL,
        null=True,
        related_name="creation_request",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=RequestStatus.values),
                name="servers_serverrequest_status_valid",
            ),
        ]

    def __str__(self):
        return f"Server request #{self.pk}"


class Membership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    server = models.ForeignKey(
        Server,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=MembershipRole,
        default=MembershipRole.STUDENT,
    )
    status = models.CharField(
        max_length=20,
        choices=MembershipStatus,
        default=MembershipStatus.ACTIVE,
    )
    joined_at = models.DateTimeField(default=timezone.now)
    last_activated_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "server"),
                name="servers_membership_unique_user_server",
            ),
            models.UniqueConstraint(
                fields=("server",),
                condition=models.Q(
                    role=MembershipRole.PRESIDENT,
                    status=MembershipStatus.ACTIVE,
                ),
                name="servers_membership_one_active_president",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=MembershipRole.values),
                name="servers_membership_role_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=MembershipStatus.values),
                name="servers_membership_status_valid",
            ),
        ]

    def __str__(self):
        return f"Membership #{self.pk}"


class MembershipSubject(models.Model):
    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name="subjects",
    )
    subject_code = models.CharField(max_length=64)
    subject_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("membership", "subject_code"),
                name="servers_membershipsubject_unique_code",
            ),
        ]

    def __str__(self):
        return self.subject_code


class JoinRequest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="join_requests",
    )
    server = models.ForeignKey(
        Server,
        on_delete=models.CASCADE,
        related_name="join_requests",
    )
    student_number = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20,
        choices=RequestStatus,
        default=RequestStatus.PENDING,
    )
    cor_file = models.CharField(max_length=255, null=True, blank=True)
    decision_reason = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="join_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "server"),
                condition=models.Q(status=RequestStatus.PENDING),
                name="servers_joinrequest_one_pending_per_user_server",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=RequestStatus.values),
                name="servers_joinrequest_status_valid",
            ),
        ]

    def __str__(self):
        return f"Join request #{self.pk}"


class JoinRequestSubject(models.Model):
    join_request = models.ForeignKey(
        JoinRequest,
        on_delete=models.CASCADE,
        related_name="subjects",
    )
    subject_code = models.CharField(max_length=64)
    subject_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("join_request", "subject_code"),
                name="servers_joinrequestsubject_unique_code",
            ),
        ]

    def __str__(self):
        return self.subject_code
