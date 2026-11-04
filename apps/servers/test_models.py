from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.servers.models import (
    JoinRequest,
    JoinRequestSubject,
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    RequestStatus,
    Server,
    ServerRequest,
)


User = get_user_model()


def create_user(email="student@example.com"):
    return User.objects.create_user(
        email=email,
        password="StrongPass123",
        full_name="Test Student",
    )


def create_server(name="Class A", slug="class-a", **kwargs):
    return Server.objects.create(name=name, slug=slug, **kwargs)


def create_join_request(user, server, **kwargs):
    return JoinRequest.objects.create(
        user=user,
        server=server,
        student_number="12345678",
        **kwargs,
    )


class ServerModelTests(TestCase):
    def test_duplicate_names_and_sections_are_allowed(self):
        create_server(name="Same Class", slug="same-class", section="1A")
        same_pair = create_server(
            name="Same Class",
            slug="same-class-2",
            section="1A",
        )
        another_section = create_server(
            name="Same Class",
            slug="same-class-3",
            section="1B",
        )

        self.assertEqual(same_pair.section, "1A")
        self.assertEqual(another_section.name, "Same Class")
        self.assertEqual(another_section.section, "1B")

    def test_slug_must_be_unique(self):
        create_server()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create_server(slug="class-a")

    def test_section_defaults_to_empty_and_can_be_stored(self):
        default_section = create_server()
        named_section = create_server(
            name="Class B",
            slug="class-b",
            section="2B",
        )

        self.assertEqual(default_section.section, "")
        self.assertEqual(named_section.section, "2B")

    def test_created_by_is_set_null_when_user_is_deleted(self):
        user = create_user()
        server = create_server(created_by=user)

        user.delete()

        server.refresh_from_db()
        self.assertIsNone(server.created_by_id)

    def test_string_representation_does_not_expose_personal_data(self):
        user = create_user("private.student@example.com")
        request = ServerRequest.objects.create(
            requester=user,
            proposed_name="Class A",
        )

        self.assertNotIn(user.email, str(request))
        self.assertNotIn(user.full_name, str(request))


class ServerRequestModelTests(TestCase):
    def setUp(self):
        self.requester = create_user()

    def test_status_defaults_to_pending(self):
        request = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Class A",
        )

        self.assertEqual(request.status, RequestStatus.PENDING)

    def test_proposed_section_defaults_to_empty_and_can_be_stored(self):
        default_section = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Class A",
        )
        sectioned_request = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Class B",
            proposed_section="3C",
        )

        self.assertEqual(default_section.proposed_section, "")
        self.assertEqual(sectioned_request.proposed_section, "3C")

    def test_invalid_status_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServerRequest.objects.create(
                    requester=self.requester,
                    proposed_name="Class A",
                    status="invalid",
                )

    def test_requester_can_have_multiple_pending_server_requests(self):
        for index in range(2):
            ServerRequest.objects.create(
                requester=self.requester,
                proposed_name=f"Class {index}",
            )

        self.assertEqual(
            ServerRequest.objects.filter(
                requester=self.requester,
                status=RequestStatus.PENDING,
            ).count(),
            2,
        )

    def test_created_server_is_set_null_when_server_is_deleted(self):
        server = create_server()
        request = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Class A",
            created_server=server,
        )

        server.delete()

        request.refresh_from_db()
        self.assertIsNone(request.created_server_id)

    def test_cor_file_accepts_null_and_storage_key(self):
        without_file = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Class A",
        )
        with_file = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Class B",
            cor_file="private/1234.pdf",
        )

        self.assertIsNone(without_file.cor_file)
        self.assertEqual(with_file.cor_file, "private/1234.pdf")

    def test_reviewed_by_is_set_null_when_user_is_deleted(self):
        reviewer = create_user("reviewer@example.com")
        request = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Class A",
            reviewed_by=reviewer,
        )

        reviewer.delete()

        request.refresh_from_db()
        self.assertIsNone(request.reviewed_by_id)


class MembershipModelTests(TestCase):
    def setUp(self):
        self.student = create_user()
        self.server = create_server()

    def test_membership_defaults_and_timestamps(self):
        membership = Membership.objects.create(
            user=self.student,
            server=self.server,
        )

        self.assertEqual(membership.role, MembershipRole.STUDENT)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertIsNotNone(membership.joined_at)
        self.assertIsNotNone(membership.last_activated_at)
        self.assertTrue(timezone.is_aware(membership.joined_at))
        self.assertTrue(timezone.is_aware(membership.last_activated_at))

    def test_user_cannot_have_two_membership_rows_for_one_server(self):
        Membership.objects.create(user=self.student, server=self.server)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(
                    user=self.student,
                    server=self.server,
                    status=MembershipStatus.LEFT,
                )

    def test_user_can_have_memberships_in_multiple_servers(self):
        Membership.objects.create(user=self.student, server=self.server)
        another_server = create_server(name="Class B", slug="class-b")
        Membership.objects.create(user=self.student, server=another_server)

        self.assertEqual(self.student.memberships.count(), 2)

    def test_only_one_active_president_is_allowed_per_server(self):
        Membership.objects.create(
            user=self.student,
            server=self.server,
            role=MembershipRole.PRESIDENT,
        )
        another_user = create_user("other@example.com")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(
                    user=another_user,
                    server=self.server,
                    role=MembershipRole.PRESIDENT,
                )

    def test_presidents_are_allowed_in_different_servers(self):
        Membership.objects.create(
            user=self.student,
            server=self.server,
            role=MembershipRole.PRESIDENT,
        )
        another_user = create_user("other@example.com")
        another_server = create_server(name="Class B", slug="class-b")
        president = Membership.objects.create(
            user=another_user,
            server=another_server,
            role=MembershipRole.PRESIDENT,
        )

        self.assertEqual(president.role, MembershipRole.PRESIDENT)

    def test_left_president_does_not_block_a_new_active_president(self):
        former_president = Membership.objects.create(
            user=self.student,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.LEFT,
        )
        new_president = Membership.objects.create(
            user=create_user("new@example.com"),
            server=self.server,
            role=MembershipRole.PRESIDENT,
        )

        self.assertEqual(former_president.status, MembershipStatus.LEFT)
        self.assertEqual(new_president.status, MembershipStatus.ACTIVE)

    def test_invalid_role_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(
                    user=self.student,
                    server=self.server,
                    role="invalid",
                )

    def test_invalid_status_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(
                    user=self.student,
                    server=self.server,
                    status="invalid",
                )

    def test_demote_then_promote_succeeds_in_one_transaction(self):
        outgoing = Membership.objects.create(
            user=self.student,
            server=self.server,
            role=MembershipRole.PRESIDENT,
        )
        incoming = Membership.objects.create(
            user=create_user("incoming@example.com"),
            server=self.server,
        )

        with transaction.atomic():
            outgoing.role = MembershipRole.STUDENT
            outgoing.save(update_fields=("role",))
            incoming.role = MembershipRole.PRESIDENT
            incoming.save(update_fields=("role",))

        outgoing.refresh_from_db()
        incoming.refresh_from_db()
        self.assertEqual(outgoing.role, MembershipRole.STUDENT)
        self.assertEqual(incoming.role, MembershipRole.PRESIDENT)


class SubjectModelTests(TestCase):
    def setUp(self):
        self.server = create_server()
        self.membership = Membership.objects.create(
            user=create_user(),
            server=self.server,
        )

    def test_membership_subject_code_is_unique_per_membership(self):
        MembershipSubject.objects.create(
            membership=self.membership,
            subject_code="CS101",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MembershipSubject.objects.create(
                    membership=self.membership,
                    subject_code="CS101",
                )

    def test_membership_subject_code_can_repeat_for_another_membership(self):
        another_membership = Membership.objects.create(
            user=create_user("another@example.com"),
            server=self.server,
        )
        MembershipSubject.objects.create(
            membership=self.membership,
            subject_code="CS101",
        )
        duplicate_code = MembershipSubject.objects.create(
            membership=another_membership,
            subject_code="CS101",
        )

        self.assertEqual(duplicate_code.subject_code, "CS101")

    def test_membership_subjects_cascade_with_membership(self):
        subject = MembershipSubject.objects.create(
            membership=self.membership,
            subject_code="CS101",
        )

        self.membership.delete()

        self.assertFalse(MembershipSubject.objects.filter(pk=subject.pk).exists())

    def test_join_request_subject_code_is_unique_per_request(self):
        request = create_join_request(
            create_user("request@example.com"),
            self.server,
        )
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS101",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                JoinRequestSubject.objects.create(
                    join_request=request,
                    subject_code="CS101",
                )

    def test_join_request_subject_code_can_repeat_for_another_request(self):
        request = create_join_request(
            create_user("request@example.com"),
            self.server,
        )
        another_request = create_join_request(
            create_user("another@example.com"),
            self.server,
        )
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS101",
        )
        duplicate_code = JoinRequestSubject.objects.create(
            join_request=another_request,
            subject_code="CS101",
        )

        self.assertEqual(duplicate_code.subject_code, "CS101")

    def test_join_request_subjects_cascade_with_request(self):
        request = create_join_request(
            create_user("request@example.com"),
            self.server,
        )
        subject = JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS101",
        )

        request.delete()

        self.assertFalse(
            JoinRequestSubject.objects.filter(pk=subject.pk).exists()
        )


class JoinRequestModelTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.server = create_server()

    def test_only_one_pending_request_is_allowed_per_user_and_server(self):
        create_join_request(self.user, self.server)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create_join_request(self.user, self.server)

    def test_new_request_is_allowed_after_rejection_or_approval(self):
        for index, status in enumerate(
            (RequestStatus.REJECTED, RequestStatus.APPROVED)
        ):
            with self.subTest(status=status):
                server = create_server(
                    name=f"Class {index}",
                    slug=f"class-{index}",
                )
                create_join_request(self.user, server, status=status)
                pending = create_join_request(self.user, server)

                self.assertEqual(pending.status, RequestStatus.PENDING)

    def test_pending_requests_are_allowed_in_different_servers(self):
        create_join_request(self.user, self.server)
        another_server = create_server(name="Class B", slug="class-b")
        another_request = create_join_request(self.user, another_server)

        self.assertEqual(another_request.status, RequestStatus.PENDING)

    def test_invalid_status_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create_join_request(self.user, self.server, status="invalid")

    def test_reviewed_by_is_set_null_when_user_is_deleted(self):
        reviewer = create_user("reviewer@example.com")
        request = create_join_request(
            self.user,
            self.server,
            reviewed_by=reviewer,
        )

        reviewer.delete()

        request.refresh_from_db()
        self.assertIsNone(request.reviewed_by_id)

    def test_cor_file_accepts_null_and_storage_key(self):
        without_file = create_join_request(
            self.user,
            self.server,
        )
        another_server = create_server(name="Class B", slug="class-b")
        with_file = create_join_request(
            self.user,
            another_server,
            cor_file="private/5678.pdf",
        )

        self.assertIsNone(without_file.cor_file)
        self.assertEqual(with_file.cor_file, "private/5678.pdf")

    def test_string_representation_does_not_expose_student_number(self):
        request = create_join_request(self.user, self.server)

        self.assertNotIn(request.student_number, str(request))
