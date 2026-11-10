# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import json
from types import SimpleNamespace
import unittest

from django.conf import settings
from django.db import OperationalError
from django.db import connection
from django.http import HttpResponse
from django.test import TestCase
from django.test import TransactionTestCase
from django.test import override_settings
from django.urls import path
from django.urls import reverse

from patchwork.middleware import is_statement_timeout
from patchwork.middleware import statement_timeout_sql
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


# A URLconf of views that misbehave on purpose, for the statement timeout
# tests below, which point ROOT_URLCONF at this module.


def timed_out_view(request):
    raise OperationalError(1969, 'Query execution was interrupted')


def broken_view(request):
    raise OperationalError(2006, 'MySQL server has gone away')


def slow_view(request):
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute('SELECT pg_sleep(3)')
        else:
            # not a bare SLEEP(): MySQL ends that early without an error when
            # it times out, and only fails a query that SLEEP() is part of
            cursor.execute(
                'SELECT COUNT(*) FROM (SELECT 1 AS n) AS t WHERE SLEEP(3) = 0'
            )
    return HttpResponse('finished')


urlpatterns = [
    path('timed-out/', timed_out_view),
    path('api/timed-out/', timed_out_view),
    path('broken/', broken_view),
    path('slow/', slow_view),
]


class StatementTimeoutSQLTest(unittest.TestCase):
    """The statements that set and reset the timeout, per database."""

    def sql(self, seconds, **conn):
        return statement_timeout_sql(SimpleNamespace(**conn), seconds)

    def test_mariadb(self):
        self.assertEqual(
            (
                'SET SESSION max_statement_time = 2.5',
                'SET SESSION max_statement_time = DEFAULT',
            ),
            self.sql(2.5, vendor='mysql', mysql_is_mariadb=True),
        )

    def test_mysql(self):
        # MySQL counts in milliseconds, and only for SELECT statements
        self.assertEqual(
            (
                'SET SESSION max_execution_time = 2500',
                'SET SESSION max_execution_time = DEFAULT',
            ),
            self.sql(2.5, vendor='mysql', mysql_is_mariadb=False),
        )

    def test_postgresql(self):
        self.assertEqual(
            ('SET statement_timeout = 2500', 'RESET statement_timeout'),
            self.sql(2.5, vendor='postgresql'),
        )

    def test_sqlite(self):
        """SQLite has no statement timeout, so there is nothing to set."""
        self.assertIsNone(self.sql(2.5, vendor='sqlite'))


class IsStatementTimeoutTest(unittest.TestCase):
    """Only a timeout may turn into a 503; other errors stay errors."""

    def test_mariadb_timeout(self):
        self.assertTrue(is_statement_timeout(OperationalError(1969, 'x')))

    def test_mysql_timeout(self):
        self.assertTrue(is_statement_timeout(OperationalError(3024, 'x')))

    def test_postgresql_timeout(self):
        class QueryCanceled(Exception):
            # what psycopg raises, reduced to the part that matters
            sqlstate = '57014'

        exc = OperationalError('canceling statement due to statement timeout')
        exc.__cause__ = QueryCanceled()
        self.assertTrue(is_statement_timeout(exc))

    def test_other_database_error(self):
        self.assertFalse(is_statement_timeout(OperationalError(2006, 'x')))

    def test_other_exception(self):
        self.assertFalse(is_statement_timeout(ValueError(1969)))


@override_settings(ROOT_URLCONF=__name__, STATEMENT_TIMEOUT=1)
class StatementTimeoutResponseTest(TestCase):
    """What a client sees when a read-only request runs out of time."""

    def test_timeout_is_503(self):
        response = self.client.get('/timed-out/')

        self.assertEqual(503, response.status_code)
        # tell clients when to come back, rather than leaving them to retry
        # immediately into the load that caused the timeout
        self.assertIn('Retry-After', response)

    def test_api_timeout_is_json(self):
        response = self.client.get('/api/timed-out/')

        self.assertEqual(503, response.status_code)
        self.assertIn('Retry-After', response)
        self.assertIn('detail', json.loads(response.content))

    def test_other_errors_are_not_hidden(self):
        with self.assertRaises(OperationalError):
            self.client.get('/broken/')

    def test_writes_are_not_retried(self):
        """A write that timed out may have done part of its work."""
        with self.assertRaises(OperationalError):
            self.client.post('/timed-out/')

    @override_settings(STATEMENT_TIMEOUT=None)
    def test_disabled(self):
        with self.assertRaises(OperationalError):
            self.client.get('/timed-out/')


@unittest.skipIf(
    connection.vendor == 'sqlite', 'SQLite has no statement timeout'
)
@override_settings(ROOT_URLCONF=__name__, STATEMENT_TIMEOUT=1)
class StatementTimeoutDatabaseTest(TransactionTestCase):
    """The timeout, end to end, against a real database server.

    Not a TestCase: in production each statement commits on its own, and
    wrapping the test in a transaction would change how PostgreSQL treats
    the failed statement.
    """

    def current_timeout(self):
        if connection.vendor == 'postgresql':
            query = 'SHOW statement_timeout'
        elif connection.mysql_is_mariadb:
            query = 'SELECT @@SESSION.max_statement_time'
        else:
            query = 'SELECT @@SESSION.max_execution_time'
        with connection.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchone()[0]

    def test_slow_query_is_stopped(self):
        default = self.current_timeout()

        response = self.client.get('/slow/')

        self.assertEqual(503, response.status_code)
        # the connection outlives the request, and so would the timeout
        self.assertEqual(default, self.current_timeout())

    def test_writes_are_not_limited(self):
        response = self.client.post('/slow/', {})

        self.assertEqual(200, response.status_code)
