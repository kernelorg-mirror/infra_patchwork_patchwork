# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from patchwork.models import Series
from patchwork.tests.utils import SAMPLE_DIFF
from patchwork.tests.utils import create_check
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_series
from patchwork.tests.utils import create_state
from patchwork.tests.utils import create_user


class SeriesDetailTest(TestCase):
    def test_absolute_url(self):
        series = create_series()

        self.assertEqual(
            series.get_absolute_url(),
            reverse('series-detail', kwargs={'series_id': series.id}),
        )

    def test_absolute_url_without_project(self):
        """A series without a project must still have a URL.

        'Series.project' is nullable and the old implementation went through
        it, so it raised for such a series. Built without touching the
        database, since the event signals will not let us save one.
        """
        series = Series(id=1, project=None)

        self.assertEqual(
            series.get_absolute_url(),
            reverse('series-detail', kwargs={'series_id': 1}),
        )

    def test_detail(self):
        series = create_series(total=2)
        patches = [
            create_patch(series=series, number=1, state=create_state()),
            create_patch(series=series, number=2, state=create_state()),
        ]

        response = self.client.get(series.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        for patch in patches:
            self.assertContains(response, patch.name)
            self.assertContains(response, patch.get_absolute_url())
            self.assertContains(response, patch.state.name)

    def test_detail_cover_letter(self):
        series = create_series()
        cover = create_cover(series=series)

        response = self.client.get(series.get_absolute_url())

        self.assertContains(response, cover.get_absolute_url())

    def test_detail_dependencies(self):
        series = create_series()
        dependency = create_series(project=series.project)
        series.add_dependencies([dependency])

        response = self.client.get(series.get_absolute_url())

        self.assertContains(response, dependency.get_absolute_url())

    def test_detail_checks(self):
        series = create_series()
        patch = create_patch(series=series, number=1)
        create_check(patch=patch)

        self.assertContains(
            self.client.get(series.get_absolute_url()), 'patchlistchecks'
        )

    def test_detail_mbox_link(self):
        series = create_series()

        self.assertContains(
            self.client.get(series.get_absolute_url()), series.get_mbox_url()
        )

    def test_detail_not_found(self):
        response = self.client.get(
            reverse('series-detail', kwargs={'series_id': 1234})
        )

        self.assertEqual(response.status_code, 404)


@override_settings(GATE_ANONYMOUS_ACCESS=True)
class SeriesDetailGatedTest(TestCase):
    def test_per_patch_state_is_shown(self):
        """State is the whole point of the limited view."""
        series = create_series()
        state = create_state(name='Under Review')
        patch = create_patch(series=series, number=1, state=state)

        response = self.client.get(series.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Under Review')
        self.assertContains(response, patch.get_absolute_url())

    def test_contents_are_hidden(self):
        series = create_series()
        create_patch(
            series=series,
            number=1,
            content='Fix all the things',
            diff=SAMPLE_DIFF,
        )

        response = self.client.get(series.get_absolute_url())

        self.assertNotContains(response, 'Fix all the things')
        self.assertNotContains(response, '@@ -0,0 +1 @@')

    def test_checks_are_hidden(self):
        series = create_series()
        patch = create_patch(series=series, number=1)
        create_check(patch=patch, context='some-ci-system')

        response = self.client.get(series.get_absolute_url())

        self.assertNotContains(response, 'some-ci-system')
        self.assertNotContains(response, 'patchlistchecks')

    def test_mbox_link_is_hidden(self):
        """The series mbox is the most expensive thing we serve."""
        series = create_series()

        self.assertNotContains(
            self.client.get(series.get_absolute_url()),
            series.get_mbox_url(),
        )

    def test_login_link(self):
        series = create_series()

        self.assertContains(
            self.client.get(series.get_absolute_url()),
            reverse('auth_login'),
        )

    def test_authenticated_user_sees_everything(self):
        series = create_series()
        patch = create_patch(series=series, number=1)
        create_check(patch=patch, context='some-ci-system')
        self.client.force_login(create_user())

        response = self.client.get(series.get_absolute_url())

        self.assertContains(response, 'patchlistchecks')
        self.assertContains(response, series.get_mbox_url())

    def test_query_count(self):
        series = create_series(total=3)
        for number in range(1, 4):
            create_patch(series=series, number=number)

        # one for the series, one for its patches, and nothing per patch
        with self.assertNumQueries(2):
            self.client.get(series.get_absolute_url())
