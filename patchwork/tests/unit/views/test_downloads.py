# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tests for the caching headers on patch, cover letter and series downloads.

Tools that apply patches fetch these over and over. An ETag lets them, and
any cache between them and us, revalidate instead of downloading again, and
the Cache-Control header says who may store a response and for how long.
"""

from django.test import TestCase
from django.urls import reverse

from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_patch_comment
from patchwork.tests.utils import create_series
from patchwork.tests.utils import create_user


class DownloadCacheTestMixin:
    # what a cache may do with the response, besides public or private
    cache_directive = None

    def create_item(self):
        raise NotImplementedError

    def url(self, item):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.item = self.create_item()

    def get(self, **headers):
        return self.client.get(self.url(self.item), headers=headers)

    def test_revalidation(self):
        """A client holding the current ETag gets an empty 304."""
        resp = self.get()
        self.assertEqual(200, resp.status_code)
        self.assertIn('ETag', resp)

        resp = self.get(if_none_match=resp['ETag'])
        self.assertEqual(304, resp.status_code)
        self.assertEqual(b'', resp.content)

    def test_etag_follows_content(self):
        """A changed download gets a new ETag, so no one is served stale."""
        etag = self.get()['ETag']

        self.item.content = 'A rewritten commit message.'
        self.item.save()

        resp = self.get(if_none_match=etag)
        self.assertEqual(200, resp.status_code)
        self.assertNotEqual(etag, resp['ETag'])

    def test_cache_control_anonymous(self):
        """Anonymous downloads may be kept by shared caches."""
        cache_control = self.get()['Cache-Control']
        self.assertIn('public', cache_control)
        self.assertIn(self.cache_directive, cache_control)

    def test_cache_control_authenticated(self):
        """Downloads by a logged-in user are kept out of shared caches.

        The content is the same either way, but a shared cache in front of an
        instance that gates anonymous access must never hand a logged-in
        user's response to anyone else.
        """
        self.client.force_login(create_user())

        cache_control = self.get()['Cache-Control']
        self.assertIn('private', cache_control)
        self.assertNotIn('public', cache_control)
        self.assertIn(self.cache_directive, cache_control)


class PatchRawDownloadTest(DownloadCacheTestMixin, TestCase):
    # a diff never changes once it has been mailed out
    cache_directive = 'max-age=86400'

    def create_item(self):
        return create_patch()

    def url(self, item):
        return reverse(
            'patch-raw',
            kwargs={
                'project_id': item.project.linkname,
                'msgid': item.encoded_msgid,
            },
        )

    def test_etag_follows_content(self):
        """A changed diff gets a new ETag, so no one is served stale."""
        etag = self.get()['ETag']

        self.item.diff = self.item.diff + '\n'
        self.item.save()

        resp = self.get(if_none_match=etag)
        self.assertEqual(200, resp.status_code)
        self.assertNotEqual(etag, resp['ETag'])


class PatchMboxDownloadTest(DownloadCacheTestMixin, TestCase):
    # tags from new replies change it, so it has to be revalidated each time
    cache_directive = 'no-cache'

    def create_item(self):
        return create_patch()

    def test_etag_follows_replies(self):
        """A reply that adds a tag gives the mbox a new ETag."""
        etag = self.get()['ETag']

        create_patch_comment(
            patch=self.item, content='Acked-by: Reviewer <r@example.com>'
        )

        resp = self.get(if_none_match=etag)
        self.assertEqual(200, resp.status_code)
        self.assertNotEqual(etag, resp['ETag'])

    def url(self, item):
        return reverse(
            'patch-mbox',
            kwargs={
                'project_id': item.project.linkname,
                'msgid': item.encoded_msgid,
            },
        )


class CoverMboxDownloadTest(DownloadCacheTestMixin, TestCase):
    cache_directive = 'no-cache'

    def create_item(self):
        return create_cover()

    def url(self, item):
        return reverse(
            'cover-mbox',
            kwargs={
                'project_id': item.project.linkname,
                'msgid': item.encoded_msgid,
            },
        )


class SeriesMboxDownloadTest(DownloadCacheTestMixin, TestCase):
    cache_directive = 'no-cache'

    def create_item(self):
        series = create_series()
        create_patch(series=series)
        return series

    def url(self, item):
        return reverse('series-mbox', kwargs={'series_id': item.id})

    def test_etag_follows_content(self):
        """A series that gains a patch gets a new ETag."""
        etag = self.get()['ETag']

        create_patch(series=self.item)

        resp = self.get(if_none_match=etag)
        self.assertEqual(200, resp.status_code)
        self.assertNotEqual(etag, resp['ETag'])
