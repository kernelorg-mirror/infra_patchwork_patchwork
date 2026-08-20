# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.conf import settings
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from patchwork.tests.utils import SAMPLE_DIFF
from patchwork.tests.utils import create_check
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_patch_comment
from patchwork.tests.utils import create_series
from patchwork.tests.utils import create_state
from patchwork.tests.utils import create_user


class DefaultsTest(TestCase):
    """The upstream default must leave every existing view untouched."""

    def test_gate_is_disabled_by_default(self):
        self.assertFalse(settings.GATE_ANONYMOUS_ACCESS)

    def test_anonymous_patch_detail_is_complete(self):
        patch = create_patch(diff=SAMPLE_DIFF)

        response = self.client.get(patch.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '@@ -0,0 +1 @@')


@override_settings(GATE_ANONYMOUS_ACCESS=True)
class SubmissionStubTest(TestCase):
    def test_patch(self):
        state = create_state(name='Under Review')
        patch = create_patch(
            state=state, content='Fix all the things', diff=SAMPLE_DIFF
        )

        response = self.client.get(patch.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, patch.name)
        self.assertContains(response, 'Under Review')
        self.assertContains(response, patch.url_msgid)
        # ... but nothing of the message itself
        self.assertNotContains(response, 'Fix all the things')
        self.assertNotContains(response, '@@ -0,0 +1 @@')

    def test_cover(self):
        cover = create_cover(content='Here is my series')

        response = self.client.get(cover.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, cover.name)
        self.assertNotContains(response, 'Here is my series')

    def test_comments_are_hidden(self):
        patch = create_patch()
        create_patch_comment(patch=patch, content='Looks good to me')

        response = self.client.get(patch.get_absolute_url())

        self.assertNotContains(response, 'Looks good to me')

    def test_checks_are_hidden(self):
        patch = create_patch()
        create_check(patch=patch, context='some-ci-system')

        response = self.client.get(patch.get_absolute_url())

        self.assertNotContains(response, 'some-ci-system')

    def test_delegate(self):
        user = create_user()
        patch = create_patch(delegate=user)

        self.assertContains(
            self.client.get(patch.get_absolute_url()), user.username
        )

    def test_series_position(self):
        series = create_series(total=12)
        patch = create_patch(series=series, number=3)

        self.assertContains(
            self.client.get(patch.get_absolute_url()), '3 of 12'
        )

    def test_login_link(self):
        patch = create_patch()
        url = patch.get_absolute_url()

        self.assertContains(self.client.get(url), reverse('auth_login'))

    def test_archive_link(self):
        patch = create_patch()

        self.assertContains(
            self.client.get(patch.get_absolute_url()),
            'https://lists.example.com/mail/%s' % patch.url_msgid,
        )

    def test_authenticated_user_sees_everything(self):
        patch = create_patch(diff=SAMPLE_DIFF)
        user = create_user()
        self.client.force_login(user)

        response = self.client.get(patch.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '@@ -0,0 +1 @@')

    def test_cover_redirect_is_preserved(self):
        """Gating must not change which URL serves which submission."""
        cover = create_cover()

        response = self.client.get(
            reverse(
                'patch-detail',
                kwargs={
                    'project_id': cover.project.linkname,
                    'msgid': cover.encoded_msgid,
                },
            )
        )

        self.assertRedirects(response, cover.get_absolute_url())

    def test_patch_redirect_is_preserved(self):
        patch = create_patch()

        response = self.client.get(
            reverse(
                'cover-detail',
                kwargs={
                    'project_id': patch.project.linkname,
                    'msgid': patch.encoded_msgid,
                },
            )
        )

        self.assertRedirects(response, patch.get_absolute_url())

    def test_missing_patch_is_still_a_404(self):
        patch = create_patch()

        response = self.client.get(
            reverse(
                'patch-detail',
                kwargs={
                    'project_id': patch.project.linkname,
                    'msgid': 'nothing@example.com',
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_query_count(self):
        patch = create_patch(delegate=create_user())

        # one for the project, one for the patch, nothing else
        with self.assertNumQueries(2):
            self.client.get(patch.get_absolute_url())

    def test_cover_query_count(self):
        cover = create_cover()

        with self.assertNumQueries(2):
            self.client.get(cover.get_absolute_url())
