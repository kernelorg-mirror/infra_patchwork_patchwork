# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tests for the list endpoints that page over IDs.

These endpoints page over bare IDs first, then fetch the full rows for just
that page, so a deep page does not make the database build and throw away
every joined row before it. That is invisible to clients, which is exactly
what needs checking: each page must hold the same items, in the same order,
as plain offset paging would give.
"""

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from patchwork.models import Cover
from patchwork.models import Patch
from patchwork.models import Series
from patchwork.tests.unit.api import utils
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_project
from patchwork.tests.utils import create_series


class PaginationOrderTestMixin:
    url_name = None
    model = None
    orders = ('id', '-id', 'name', '-name')

    def create_item(self, project, name):
        raise NotImplementedError

    def test_list_pagination_order(self):
        """A page holds the right items, in order, for every ordering."""
        project = create_project()
        for name in ('d', 'a', 'e', 'b', 'c'):
            self.create_item(project, name)
        # must not leak through the project filter
        self.create_item(create_project(), 'f')

        for order in self.orders:
            with self.subTest(order=order):
                expected = list(
                    self.model.objects.filter(project=project)
                    .order_by(order)
                    .values_list('id', flat=True)
                )[2:4]
                resp = self.client.get(
                    reverse(self.url_name),
                    {
                        'project': project.pk,
                        'order': order,
                        'per_page': 2,
                        'page': 2,
                    },
                )
                self.assertEqual(status.HTTP_200_OK, resp.status_code)
                self.assertEqual(expected, [x['id'] for x in resp.data])
                self.assertIn('rel="next"', resp['Link'])
                self.assertIn('rel="prev"', resp['Link'])


@override_settings(ENABLE_REST_API=True)
class TestPatchPagination(PaginationOrderTestMixin, utils.APITestCase):
    url_name = 'api-patch-list'
    model = Patch

    def create_item(self, project, name):
        return create_patch(project=project, name=name)


@override_settings(ENABLE_REST_API=True)
class TestCoverPagination(PaginationOrderTestMixin, utils.APITestCase):
    url_name = 'api-cover-list'
    model = Cover

    def create_item(self, project, name):
        return create_cover(project=project, name=name)


@override_settings(ENABLE_REST_API=True)
class TestSeriesPagination(PaginationOrderTestMixin, utils.APITestCase):
    url_name = 'api-series-list'
    model = Series

    def create_item(self, project, name):
        series = create_series(project=project, name=name)
        # the schema does not allow a series without a cover letter
        create_cover(series=series)
        return series
