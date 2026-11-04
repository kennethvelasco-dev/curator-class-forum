from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.channels.models import Channel, ChannelType
from apps.servers.models import Server


class ChannelModelTests(TestCase):
    def setUp(self):
        self.server = Server.objects.create(name="Class A", slug="class-a")

    def create_channel(
        self,
        name="Announcements",
        slug="announcements",
        channel_type=ChannelType.ANNOUNCEMENTS,
        server=None,
    ):
        return Channel.objects.create(
            server=server or self.server,
            name=name,
            slug=slug,
            channel_type=channel_type,
        )

    def test_server_and_slug_must_be_unique_together(self):
        self.create_channel()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_channel(
                    name="Other announcements",
                    channel_type=ChannelType.RULES,
                )

    def test_default_channel_type_is_unique_per_server(self):
        self.create_channel()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_channel(
                    name="Announcements copy",
                    slug="announcements-copy",
                )

    def test_default_channel_type_can_repeat_in_another_server(self):
        self.create_channel()
        another_server = Server.objects.create(
            name="Class B",
            slug="class-b",
        )
        channel = self.create_channel(server=another_server)

        self.assertEqual(channel.channel_type, ChannelType.ANNOUNCEMENTS)

    def test_several_subject_channels_are_allowed_per_server(self):
        first = self.create_channel(
            name="Computer Science",
            slug="computer-science",
            channel_type=ChannelType.SUBJECT,
        )
        second = self.create_channel(
            name="Mathematics",
            slug="mathematics",
            channel_type=ChannelType.SUBJECT,
        )

        self.assertEqual(first.channel_type, ChannelType.SUBJECT)
        self.assertEqual(second.channel_type, ChannelType.SUBJECT)

    def test_invalid_channel_type_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_channel(channel_type="invalid")

    def test_channels_cascade_with_server(self):
        channel = self.create_channel()

        self.server.delete()

        self.assertFalse(Channel.objects.filter(pk=channel.pk).exists())

    def test_string_representation_uses_channel_name(self):
        channel = self.create_channel()

        self.assertEqual(str(channel), channel.name)
