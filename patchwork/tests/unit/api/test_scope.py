# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tests for REST_RESTRICT_UNSCOPED_QUERIES.

A substring search or an ordering that no index can serve is cheap within one
project and a full table scan across all of them. These tests pin down which
list requests the setting turns away, and - just as important - that it never
gets in the way of requests that are already cheap.
"""

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from patchwork.tests.unit.api import utils
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_project
from patchwork.tests.utils import create_series


class ScopeTestMixin:
    """Shared tests, run once per scoped list endpoint.

    Subclasses describe the endpoint: how to create an item, which query
    parameters scope it, and which orderings stay cheap without a scope.
    """

    url_name = None
    scope_params = ()
    # an ordering that needs a scope, and ones that never do
    scoped_ordering = 'name'
    unscoped_orderings = ('id', '-id')

    def create_item(self, project, name):
        raise NotImplementedError

    def scope_value(self, param, item):
        """The query value for 'param' that matches 'item'."""
        if param == 'project':
            return item.project.linkname
        return item.series.id

    def setUp(self):
        super().setUp()
        self.project = create_project()
        self.item = self.create_item(self.project, 'needle in a haystack')
        self.create_item(create_project(), 'needle elsewhere')
        self.create_item(self.project, 'haystack only')

    def get(self, **params):
        return self.client.get(reverse(self.url_name), params)

    def assertRejected(self, resp):
        self.assertEqual(status.HTTP_400_BAD_REQUEST, resp.status_code)
        # name the fix, so whoever wrote the client knows what to change
        for param in self.scope_params:
            self.assertIn(param, resp.data['detail'])

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=False)
    def test_unrestricted_by_default(self):
        """Without the setting, unscoped searches and orderings still work."""
        resp = self.get(q='needle')
        self.assertEqual(status.HTTP_200_OK, resp.status_code)
        self.assertEqual(2, len(resp.data))

        resp = self.get(order=self.scoped_ordering)
        self.assertEqual(status.HTTP_200_OK, resp.status_code)

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=True)
    def test_listing_unaffected(self):
        """A plain listing with no search or ordering is never turned away."""
        resp = self.get()
        self.assertEqual(status.HTTP_200_OK, resp.status_code)
        self.assertEqual(3, len(resp.data))

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=True)
    def test_unscoped_search_rejected(self):
        """A search across every project is turned away."""
        self.assertRejected(self.get(q='needle'))

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=True)
    def test_scoped_search_allowed(self):
        """Any one of the scoping parameters makes a search acceptable."""
        for param in self.scope_params:
            with self.subTest(param=param):
                resp = self.get(
                    q='needle', **{param: self.scope_value(param, self.item)}
                )
                self.assertEqual(status.HTTP_200_OK, resp.status_code)
                self.assertEqual([self.item.id], [x['id'] for x in resp.data])

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=True)
    def test_unscoped_ordering_rejected(self):
        """An ordering no index can serve is turned away without a scope."""
        for order in (self.scoped_ordering, '-' + self.scoped_ordering):
            with self.subTest(order=order):
                self.assertRejected(self.get(order=order))

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=True)
    def test_unscoped_index_ordering_allowed(self):
        """Orderings an index can serve need no scope."""
        for order in self.unscoped_orderings:
            with self.subTest(order=order):
                resp = self.get(order=order)
                self.assertEqual(status.HTTP_200_OK, resp.status_code)

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=True)
    def test_scoped_ordering_allowed(self):
        """Within a scope, every ordering is allowed again."""
        resp = self.get(
            order=self.scoped_ordering,
            project=self.project.linkname,
        )
        self.assertEqual(status.HTTP_200_OK, resp.status_code)
        self.assertEqual(2, len(resp.data))

    @override_settings(REST_RESTRICT_UNSCOPED_QUERIES=True)
    def test_unknown_ordering_ignored(self):
        """Unknown fields are still ignored rather than rejected.

        That is how DRF treats them, and they fall back to the default
        ordering, which is always cheap.
        """
        resp = self.get(order='bogus')
        self.assertEqual(status.HTTP_200_OK, resp.status_code)


@override_settings(ENABLE_REST_API=True)
class TestPatchScope(ScopeTestMixin, utils.APITestCase):
    url_name = 'api-patch-list'
    scope_params = ('project', 'series')

    def create_item(self, project, name):
        return create_patch(project=project, name=name)


@override_settings(ENABLE_REST_API=True)
class TestCoverScope(ScopeTestMixin, utils.APITestCase):
    url_name = 'api-cover-list'
    scope_params = ('project', 'series')
    # the cover covering index leads with the date
    unscoped_orderings = ('id', '-id', 'date', '-date')

    def create_item(self, project, name):
        return create_cover(project=project, name=name)


@override_settings(ENABLE_REST_API=True)
class TestSeriesScope(ScopeTestMixin, utils.APITestCase):
    url_name = 'api-series-list'
    scope_params = ('project',)

    def create_item(self, project, name):
        series = create_series(project=project, name=name)
        # the schema does not allow a series without a cover letter
        create_cover(series=series)
        return series
