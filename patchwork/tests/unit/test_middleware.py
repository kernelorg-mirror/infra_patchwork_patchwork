# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.conf import settings
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from patchwork.tests.utils import create_bundle
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_project
from patchwork.tests.utils import create_series
from patchwork.tests.utils import create_user


class GateAnonymousAccessMiddlewareTest(TestCase):
    """The URL matrix: who the gate lets through, and who it stops."""

    def setUp(self):
        self.project = create_project()
        self.patch = create_patch(project=self.project)
        self.cover = create_cover(project=self.project)
        self.series = create_series(project=self.project)
        self.bundle_owner = create_user()
        self.bundle = create_bundle(
            owner=self.bundle_owner, project=self.project
        )

    def _allowed_urls(self):
        return [
            reverse('project-list'),
            reverse(
                'patch-list', kwargs={'project_id': self.project.linkname}
            ),
            reverse(
                'patch-detail',
                kwargs={
                    'project_id': self.project.linkname,
                    'msgid': self.patch.encoded_msgid,
                },
            ),
            reverse(
                'cover-detail',
                kwargs={
                    'project_id': self.project.linkname,
                    'msgid': self.cover.encoded_msgid,
                },
            ),
            reverse('series-detail', kwargs={'series_id': self.series.id}),
            reverse(
                'msgid-lookup', kwargs={'msgid': self.patch.encoded_msgid}
            ),
            reverse('about'),
            reverse(
                'pwclientrc', kwargs={'project_id': self.project.linkname}
            ),
            reverse('auth_login'),
            reverse('auth_logout'),
            reverse('password_reset'),
            reverse('user-register'),
            reverse('confirm', kwargs={'key': 'deadbeef'}),
            reverse('mail-settings'),
        ]

    def _gated_urls(self):
        return [
            reverse(
                'bundle-detail',
                kwargs={
                    'username': self.bundle_owner.username,
                    'bundlename': self.bundle.name,
                },
            ),
            reverse('comment-redirect', kwargs={'comment_id': 999999}),
            reverse('patch-id-redirect', kwargs={'patch_id': self.patch.id}),
            reverse('cover-id-redirect', kwargs={'cover_id': self.cover.id}),
            reverse('api-submitters'),
            reverse('api-delegates'),
        ]

    def _assertNotLoginRedirect(self, response, url):
        # some of these views issue their own, unrelated 302s (the legacy
        # /patch/<id>/ redirect, for one), so the interesting question is
        # never "is this a redirect" but "is this THE login redirect"
        is_login_redirect = response.status_code == 302 and response[
            'Location'
        ].startswith(reverse('auth_login'))
        self.assertFalse(is_login_redirect, '%s was sent to log in' % url)

    def test_gate_is_disabled_by_default(self):
        self.assertFalse(settings.GATE_ANONYMOUS_ACCESS)

        for url in self._gated_urls():
            self._assertNotLoginRedirect(self.client.get(url), url)

    @override_settings(GATE_ANONYMOUS_ACCESS=True)
    def test_allowlisted_urls_are_reachable_when_gated(self):
        for url in self._allowed_urls():
            self._assertNotLoginRedirect(self.client.get(url), url)

    @override_settings(GATE_ANONYMOUS_ACCESS=True)
    def test_other_urls_are_gated(self):
        for url in self._gated_urls():
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                302,
                '%s was not gated' % url,
            )
            self.assertTrue(
                response['Location'].startswith(reverse('auth_login')),
                '%s redirected to %s instead of the login page'
                % (url, response['Location']),
            )

    @override_settings(GATE_ANONYMOUS_ACCESS=True)
    def test_authenticated_user_bypasses_the_gate(self):
        self.client.force_login(create_user())

        for url in self._gated_urls():
            self._assertNotLoginRedirect(self.client.get(url), url)

    @override_settings(GATE_ANONYMOUS_ACCESS=True)
    def test_xmlrpc_is_not_gated(self):
        if not settings.ENABLE_XMLRPC:
            self.skipTest('ENABLE_XMLRPC is disabled')

        response = self.client.get(reverse('xmlrpc'))

        self.assertNotEqual(response.status_code, 302)

    @override_settings(GATE_ANONYMOUS_ACCESS=True)
    def test_rest_api_is_not_gated(self):
        if not settings.ENABLE_REST_API:
            self.skipTest('ENABLE_REST_API is disabled')

        response = self.client.get(reverse('api-index'))

        self.assertNotEqual(response.status_code, 302)

    @override_settings(GATE_ANONYMOUS_ACCESS=True)
    def test_gated_redirect_preserves_next(self):
        url = reverse(
            'bundle-detail',
            kwargs={
                'username': self.bundle_owner.username,
                'bundlename': self.bundle.name,
            },
        )

        response = self.client.get(url)

        self.assertIn('next=%s' % url, response['Location'])
