# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tests for the state of patches embedded in other resources.

Since API v1.5 an embedded patch carries its state, so that a client
following a series, bundle or event does not have to fetch every patch in
it just to learn where each one stands. The same embedded patch appears in
four places; each is checked for the field itself, for older versions
staying unchanged, and for the state not costing a query per patch.
"""

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from patchwork.models import Event
from patchwork.tests.unit.api import utils
from patchwork.tests.utils import create_bundle
from patchwork.tests.utils import create_cover
from patchwork.tests.utils import create_patch
from patchwork.tests.utils import create_patches
from patchwork.tests.utils import create_relation
from patchwork.tests.utils import create_series
from patchwork.tests.utils import create_state


class EmbeddedStateTestMixin:
    def create_items(self, count):
        """Create 'count' embedded patches; return those patches."""
        raise NotImplementedError

    def get(self, version):
        raise NotImplementedError

    def embedded_patches(self, data):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.state = create_state(name='Under Review', slug='under-review')

    def test_state_included(self):
        """Embedded patches carry their state's slug from v1.5."""
        patches = self.create_items(2)

        resp = self.get('1.5')
        self.assertEqual(
            {patch.id: patch.state.slug for patch in patches},
            {x['id']: x['state'] for x in self.embedded_patches(resp.data)},
        )

    def test_state_hidden_before_1_5(self):
        """Older versions keep the embedded patch they always had."""
        self.create_items(2)

        resp = self.get('1.4')
        embedded = self.embedded_patches(resp.data)
        self.assertEqual(2, len(embedded))
        for patch in embedded:
            self.assertNotIn('state', patch)

    def test_no_query_per_patch(self):
        """The state costs the same number of queries for any patch count."""
        self.create_items(1)
        with CaptureQueriesContext(connection) as one:
            self.get('1.5')

        self.create_items(2)
        with CaptureQueriesContext(connection) as three:
            resp = self.get('1.5')

        self.assertEqual(3, len(self.embedded_patches(resp.data)))
        self.assertEqual(len(one), len(three))


@override_settings(ENABLE_REST_API=True)
class TestSeriesEmbeddedState(EmbeddedStateTestMixin, utils.APITestCase):
    def create_items(self, count):
        patches = []
        for _ in range(count):
            series = create_series()
            # the schema does not allow a series without a cover letter
            create_cover(series=series)
            patches.append(create_patch(series=series, state=self.state))
        return patches

    def get(self, version):
        return self.client.get(
            reverse('api-series-list', kwargs={'version': version})
        )

    def embedded_patches(self, data):
        return [patch for series in data for patch in series['patches']]


@override_settings(ENABLE_REST_API=True)
class TestBundleEmbeddedState(EmbeddedStateTestMixin, utils.APITestCase):
    def create_items(self, count):
        patches = []
        for _ in range(count):
            bundle = create_bundle(public=True)
            patch = create_patch(project=bundle.project, state=self.state)
            bundle.append_patch(patch)
            patches.append(patch)
        return patches

    def get(self, version):
        return self.client.get(
            reverse('api-bundle-list', kwargs={'version': version})
        )

    def embedded_patches(self, data):
        return [patch for bundle in data for patch in bundle['patches']]


@override_settings(ENABLE_REST_API=True)
class TestEventEmbeddedState(EmbeddedStateTestMixin, utils.APITestCase):
    def create_items(self, count):
        # creating a patch raises a 'patch-created' event for it
        return [create_patch(state=self.state) for _ in range(count)]

    def get(self, version):
        return self.client.get(
            reverse('api-event-list', kwargs={'version': version}),
            {'category': Event.CATEGORY_PATCH_CREATED},
        )

    def embedded_patches(self, data):
        return [event['payload']['patch'] for event in data]


@override_settings(ENABLE_REST_API=True)
class TestRelatedEmbeddedState(EmbeddedStateTestMixin, utils.APITestCase):
    def setUp(self):
        super().setUp()
        self.relation = create_relation()
        self.patch = create_patch(related=self.relation)

    def create_items(self, count):
        return create_patches(count, related=self.relation, state=self.state)

    def get(self, version):
        return self.client.get(
            reverse(
                'api-patch-detail',
                kwargs={'version': version, 'pk': self.patch.id},
            )
        )

    def embedded_patches(self, data):
        return data['related']
