# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib import messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.cache import cache
from django.db import OperationalError
from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from patchwork.views import anonymous

from patchwork.tests.utils import SAMPLE_DIFF
from patchwork.tests.utils import create_check
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_patch_comment
from patchwork.tests.utils import create_project
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

    def test_anonymous_patch_list_is_complete(self):
        patch = create_patch()

        response = self.client.get(
            reverse(
                'patch-list',
                kwargs={'project_id': patch.project.linkname},
            ),
            {'state': 'action-required'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, patch.name)
        self.assertNotContains(response, 'limited view')


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


CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        # a location of our own, so that we cannot evict or read anything
        # another test put in the default cache
        'LOCATION': 'patchwork-anonymous-list-tests',
    }
}


@override_settings(GATE_ANONYMOUS_ACCESS=True, CACHES=CACHES)
class SeriesListTest(TestCase):
    """The limited, cacheable listing served in place of the patch list."""

    def setUp(self):
        # the test runner does not clear the cache between tests, and the
        # whole point of this view is that it remembers things
        cache.clear()
        self.state = create_state(name='New', action_required=True)
        self.done = create_state(name='Accepted', action_required=False)
        self.project = create_project()

    def _series(self, states, **kwargs):
        series = create_series(project=self.project, total=len(states))
        for i, state in enumerate(states):
            create_patch(series=series, state=state, number=i + 1)
        return series

    @property
    def url(self):
        return reverse(
            'patch-list', kwargs={'project_id': self.project.linkname}
        )

    def test_series_are_listed(self):
        series = self._series([self.state])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, series.get_absolute_url())
        self.assertContains(response, 'New')
        self.assertContains(response, series.submitter.name)

    def test_patch_contents_are_not_listed(self):
        series = create_series(project=self.project, total=1)
        create_patch(series=series, state=self.state, diff=SAMPLE_DIFF)

        response = self.client.get(self.url)

        # the series name comes from the patch subject, so that is expected
        # to show up; nothing else about the patch is
        self.assertNotContains(response, '@@ -0,0 +1 @@')
        self.assertNotContains(response, 'patch-list-form')

    def test_inactive_series_are_omitted(self):
        active = self._series([self.state])
        inactive = self._series([self.done])

        response = self.client.get(self.url)

        self.assertContains(response, active.get_absolute_url())
        self.assertNotContains(response, inactive.get_absolute_url())

    def test_series_are_listed_once(self):
        """A series is one row, however many of its patches need action."""
        one = self._series([self.state])
        many = self._series([self.state, self.state, self.state])

        content = self.client.get(self.url).content.decode()

        self.assertEqual(
            content.count(one.get_absolute_url()),
            content.count(many.get_absolute_url()),
        )

    def test_mixed_state(self):
        self._series([self.state, self.done])

        response = self.client.get(self.url)

        self.assertContains(response, 'Mixed')
        self.assertNotContains(response, '>New<')

    def test_partially_received_series(self):
        series = create_series(project=self.project, total=5)
        create_patch(series=series, state=self.state, number=1)

        response = self.client.get(self.url)

        self.assertContains(response, '1 of 5')

    def test_empty_project(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no series awaiting action')

    @override_settings(ANONYMOUS_LIST_MAX_SERIES=2)
    def test_series_are_capped_newest_first(self):
        older = [self._series([self.state]) for _ in range(3)]

        response = self.client.get(self.url)

        # create_series stamps 'now', so the last one created is the newest
        self.assertNotContains(response, older[0].get_absolute_url())
        self.assertContains(response, older[1].get_absolute_url())
        self.assertContains(response, older[2].get_absolute_url())

    def test_other_projects_are_omitted(self):
        mine = self._series([self.state])
        theirs = create_series(project=create_project(), total=1)
        create_patch(series=theirs, state=self.state)

        response = self.client.get(self.url)

        self.assertContains(response, mine.get_absolute_url())
        self.assertNotContains(response, theirs.get_absolute_url())

    def test_query_string_is_redirected(self):
        response = self.client.get(self.url, {'state': 'new', 'page': '4'})

        self.assertRedirects(response, self.url, status_code=302)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_query_count(self):
        self._series([self.state, self.state])
        self._series([self.state])

        # the project, the series, and the state roll-up
        with self.assertNumQueries(3):
            self.client.get(self.url)

        # ... and only the project once the render is cached
        with self.assertNumQueries(1):
            self.client.get(self.url)

    def test_query_count_is_independent_of_size(self):
        for _ in range(5):
            self._series([self.state, self.state, self.done])

        with self.assertNumQueries(3):
            self.client.get(self.url)

    def test_response_is_cached(self):
        self.client.get(self.url)
        new = self._series([self.state])

        response = self.client.get(self.url)

        self.assertNotContains(response, new.get_absolute_url())

    def test_cache_is_per_project(self):
        mine = self._series([self.state])
        other = create_project()
        theirs = create_series(project=other, total=1)
        create_patch(series=theirs, state=self.state)

        self.client.get(self.url)
        response = self.client.get(
            reverse('patch-list', kwargs={'project_id': other.linkname})
        )

        self.assertContains(response, theirs.get_absolute_url())
        self.assertNotContains(response, mine.get_absolute_url())

    def _clock(self):
        """Patch the view's clock; returns a list holding 'now'."""
        now = [1_000_000.0]
        patcher = mock.patch.object(anonymous, 'time')
        self.addCleanup(patcher.stop)
        patcher.start().time.side_effect = lambda: now[0]
        return now

    def test_max_age_counts_down(self):
        """A shared cache is told how long the copy has left, not a full TTL.

        Otherwise a copy fetched just before it went stale would be kept for
        another full interval, twice as stale as the page says it may be.
        """
        now = self._clock()
        self.client.get(self.url)

        now[0] += 100
        response = self.client.get(self.url)

        self.assertEqual(response['Cache-Control'], 'public, max-age=200')

    def test_expired_copy_is_rerendered(self):
        now = self._clock()
        self.client.get(self.url)
        new = self._series([self.state])

        now[0] += 301
        response = self.client.get(self.url)

        self.assertContains(response, new.get_absolute_url())
        self.assertEqual(response['Cache-Control'], 'public, max-age=300')
        self.assertIsNone(cache.get(anonymous._lock_key(self.project)))

    def test_stale_copy_served_while_another_render_runs(self):
        """Only one worker re-renders; the rest serve the old copy.

        Without that, every request arriving while the copy is stale would
        run the same expensive query at once.
        """
        now = self._clock()
        self.client.get(self.url)
        new = self._series([self.state])

        now[0] += 301
        # another worker is already rendering
        cache.add(anonymous._lock_key(self.project), True)
        # the project lookup, and nothing else
        with self.assertNumQueries(1):
            response = self.client.get(self.url)

        self.assertNotContains(response, new.get_absolute_url())
        # stale already: no one downstream should keep it
        self.assertEqual(response['Cache-Control'], 'public, max-age=0')

    def test_failed_render_keeps_serving_the_stale_copy(self):
        """A render that fails, say on a statement timeout, keeps the lock.

        The other workers go on serving the old copy until the lock expires,
        rather than all retrying the query against a struggling database.
        """
        now = self._clock()
        self.client.get(self.url)

        now[0] += 301
        with mock.patch.object(
            anonymous,
            '_render_series_list',
            side_effect=OperationalError(1969, 'interrupted'),
        ):
            with self.assertRaises(OperationalError):
                self.client.get(self.url)

        new = self._series([self.state])
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, new.get_absolute_url())

    def test_first_render_is_not_repeated_by_others(self):
        """With no copy to serve, the other workers ask the client to wait.

        Until a project's first render finishes there is nothing to fall
        back on, and that is when a render is slowest: letting every request
        run it would multiply the one query the cache exists to bound.
        """
        self._series([self.state])
        # another worker is already rendering
        cache.add(anonymous._lock_key(self.project), True)

        # the project lookup, and nothing else
        with self.assertNumQueries(1):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 503)
        self.assertIn('Retry-After', response)
        # the next request should get the listing, not this
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_failed_first_render_is_not_retried_at_once(self):
        """A first render that fails keeps the lock, like any other.

        With no copy stored, nothing else stops each following request from
        running the query that just failed.
        """
        self._series([self.state])
        with mock.patch.object(
            anonymous,
            '_render_series_list',
            side_effect=OperationalError(1969, 'interrupted'),
        ) as render:
            with self.assertRaises(OperationalError):
                self.client.get(self.url)
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(render.call_count, 1)

    def test_copy_from_another_release_is_ignored(self):
        """A copy cached by a release that stored it differently is not read.

        A shared cache outlives an upgrade, and what it holds must not break
        the listing until it expires.
        """
        series = self._series([self.state])
        cache.set('anon-series-list:%d' % self.project.id, b'<html></html>')

        response = self.client.get(self.url)

        self.assertContains(response, series.get_absolute_url())

    def test_cacheable_by_a_shared_cache(self):
        self._series([self.state])

        response = self.client.get(self.url)

        self.assertEqual(response['Cache-Control'], 'public, max-age=300')
        # Varnish and friends refuse to cache a response that sets a cookie,
        # and a CSRF token in a shared body would be worse than useless
        self.assertNotIn('Set-Cookie', response)
        self.assertNotContains(response, 'csrfmiddlewaretoken')

    def test_authenticated_user_does_not_see_the_cached_body(self):
        self._series([self.state])
        self.client.get(self.url)

        user = create_user()
        self.client.force_login(user)
        response = self.client.get(self.url)

        self.assertContains(response, 'patch-list-form')
        self.assertNotContains(response, 'limited view')

    def test_authenticated_render_does_not_enter_the_cache(self):
        self._series([self.state])

        user = create_user()
        self.client.force_login(user)
        self.client.get(self.url)
        self.client.logout()

        response = self.client.get(self.url)

        self.assertContains(response, 'limited view')
        self.assertNotContains(response, 'patch-list-form')

    def test_pending_messages_bypass_the_cache(self):
        self._series([self.state])

        request = RequestFactory().get(self.url)
        request.user = AnonymousUser()
        request.session = {}
        request._messages = FallbackStorage(request)
        messages.info(request, 'a message for one person only')

        response = anonymous.series_list(request, self.project)

        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertIsNone(cache.get('anon-series-list:%d' % self.project.id))
        # len() does not mark messages as read, so this one is still waiting
        self.assertEqual(len(request._messages), 1)
