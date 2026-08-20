# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from patchwork.tests.utils import SAMPLE_DIFF
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_project
from patchwork.tests.utils import create_series
from patchwork.tests.utils import create_state
from patchwork.tests.utils import create_user

MSGID = '<20260820.1234@example.com>'
TRIMMED_MSGID = '20260820.1234@example.com'


class MsgidLookupTest(TestCase):
    def _get(self, msgid=TRIMMED_MSGID):
        return self.client.get(
            reverse('msgid-lookup', kwargs={'msgid': msgid})
        )

    def test_single_project(self):
        state = create_state(name='Under Review')
        patch = create_patch(msgid=MSGID, state=state)

        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, patch.project.name)
        self.assertContains(response, 'Under Review')
        self.assertContains(response, patch.get_absolute_url())

    def test_multiple_projects(self):
        # the same series delivered to two lists tracked here: one row per
        # project, each with its own state
        states = [create_state(name='New'), create_state(name='Queued')]
        patches = [
            create_patch(
                msgid=MSGID, project=create_project(), state=states[0]
            ),
            create_patch(
                msgid=MSGID, project=create_project(), state=states[1]
            ),
        ]

        response = self._get()

        self.assertEqual(response.status_code, 200)
        for patch in patches:
            self.assertContains(response, patch.project.name)
            self.assertContains(response, patch.get_absolute_url())
        self.assertContains(response, 'New')
        self.assertContains(response, 'Queued')

    def test_single_project_does_not_redirect(self):
        """A single hit must render the same page as multiple hits.

        The result set can grow later, when the patch is picked up by a
        second project, and a URL we hand out must not change behaviour
        under people who bookmarked it.
        """
        create_patch(msgid=MSGID)

        self.assertEqual(self._get().status_code, 200)

    def test_cover(self):
        cover = create_cover(msgid=MSGID)

        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cover letter')
        self.assertContains(response, cover.get_absolute_url())

    def test_patch_and_cover(self):
        patch = create_patch(msgid=MSGID, project=create_project())
        cover = create_cover(msgid=MSGID, project=create_project())

        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, patch.get_absolute_url())
        self.assertContains(response, cover.get_absolute_url())

    def test_delegate(self):
        user = create_user()
        create_patch(msgid=MSGID, delegate=user)

        self.assertContains(self._get(), user.username)

    def test_series_position(self):
        series = create_series(total=12)
        create_patch(msgid=MSGID, series=series, number=3)

        self.assertContains(self._get(), '3 of 12')

    def test_archive_link(self):
        project = create_project(
            list_archive_url_format='https://lists.example.com/mail/{}'
        )
        create_patch(msgid=MSGID, project=project)

        self.assertContains(
            self._get(),
            'https://lists.example.com/mail/%s' % TRIMMED_MSGID,
        )

    def test_no_content_disclosure(self):
        """The lookup shows metadata only, never the patch itself."""
        create_patch(msgid=MSGID, content='Hello, world.', diff=SAMPLE_DIFF)

        response = self._get()

        self.assertNotContains(response, 'Hello, world.')
        self.assertNotContains(response, '@@ -0,0 +1 @@')

    def test_not_found(self):
        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not tracked by Patchwork')

    @override_settings(DEFAULT_ARCHIVE_URL_FORMAT=None)
    def test_not_found_without_archive_url_format(self):
        self.assertNotContains(self._get(), 'mailing list archive')

    @override_settings(DEFAULT_ARCHIVE_URL_FORMAT='https://lore.kernel.org/{}')
    def test_not_found_with_archive_url_format(self):
        self.assertContains(
            self._get(), 'https://lore.kernel.org/%s' % TRIMMED_MSGID
        )

    def test_msgid_with_slash(self):
        msgid = '<2026/08/20.1234@example.com>'
        patch = create_patch(msgid=msgid)

        # both the raw form and the percent-encoded form used elsewhere in
        # patchwork URLs must resolve
        for url in (
            '/m/2026/08/20.1234@example.com/',
            '/m/2026%2F08%2F20.1234@example.com/',
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, patch.project.name)

    def test_query_count_hit(self):
        create_patch(msgid=MSGID, delegate=create_user())

        # one query for patches, one for covers, and nothing per row
        with self.assertNumQueries(2):
            self._get()

    def test_query_count_miss(self):
        # the path crawlers take must not get more expensive than a hit
        with self.assertNumQueries(2):
            self._get()
