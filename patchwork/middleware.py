# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import logging

from django.conf import settings
from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.db import DatabaseError
from django.db import connection
from django.http import HttpResponse
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# Long enough for whatever overloaded the database to have a chance to pass,
# instead of clients retrying straight back into it.
STATEMENT_TIMEOUT_RETRY_AFTER = 60

# MariaDB's ER_STATEMENT_TIMEOUT, MySQL's ER_QUERY_TIMEOUT
MYSQL_TIMEOUT_ERRORS = (1969, 3024)
# PostgreSQL's query_canceled, which statement_timeout raises
POSTGRESQL_TIMEOUT_SQLSTATE = '57014'


class GateAnonymousAccessMiddleware(LoginRequiredMiddleware):
    """A ``LoginRequiredMiddleware`` that no-ops unless configured on.

    ``LoginRequiredMiddleware`` itself has no such switch, and settings-time
    ``MIDDLEWARE`` composition cannot practically be overridden per test, so
    this is what lets ``override_settings(GATE_ANONYMOUS_ACCESS=True)`` work.
    It is otherwise installed unconditionally.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not settings.GATE_ANONYMOUS_ACCESS:
            return None

        # TODO(gate-anonymous-access): the REST and XML-RPC APIs are left
        # alone for now; they get their own authentication requirement
        # (DEFAULT_PERMISSION_CLASSES) in a later change, rather than being
        # gated by session login here.
        if request.path_info.startswith('/api/'):
            return None

        return super().process_view(request, view_func, view_args, view_kwargs)


def statement_timeout_sql(conn, seconds):
    """Return the statements that set and reset a statement timeout.

    Returns None for databases without one, such as SQLite.
    """
    # float() keeps anything but a number from reaching the SQL
    seconds = float(seconds)
    milliseconds = int(seconds * 1000)

    if conn.vendor == 'postgresql':
        return (
            'SET statement_timeout = %d' % milliseconds,
            'RESET statement_timeout',
        )

    if conn.vendor == 'mysql':
        if conn.mysql_is_mariadb:
            return (
                'SET SESSION max_statement_time = %g' % seconds,
                'SET SESSION max_statement_time = DEFAULT',
            )
        # unlike MariaDB's, this only applies to SELECT statements
        return (
            'SET SESSION max_execution_time = %d' % milliseconds,
            'SET SESSION max_execution_time = DEFAULT',
        )

    return None


def is_statement_timeout(exc):
    """Whether an exception is the database giving up on a statement."""
    if not isinstance(exc, DatabaseError):
        return False

    # Django keeps the driver's arguments, which for MySQL start with the
    # error number, and chains the driver's own exception
    if exc.args and exc.args[0] in MYSQL_TIMEOUT_ERRORS:
        return True

    cause = exc.__cause__
    return (
        getattr(cause, 'sqlstate', None) == POSTGRESQL_TIMEOUT_SQLSTATE
        or getattr(cause, 'pgcode', None) == POSTGRESQL_TIMEOUT_SQLSTATE
    )


class StatementTimeoutMiddleware:
    """Limit how long one statement may run while serving a read.

    One expensive request repeated in a loop can keep every worker waiting
    on the database, and the database busy with queries whose clients have
    long given up. A timeout ends such a query early, and the client is told
    to come back later with a 503 and Retry-After, which well-behaved
    clients honour, rather than with a 500, which most retry at once.

    Only reads are limited. A write that is stopped part way may already
    have done some of its work, and writes are not what crawlers repeat.
    The timeout is set per request rather than per connection so that it
    never applies to management commands, which can legitimately run long
    statements - building an index during a migration, for one.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _applies(self, request):
        return bool(settings.STATEMENT_TIMEOUT) and request.method in (
            'GET',
            'HEAD',
            'OPTIONS',
        )

    def __call__(self, request):
        if not self._applies(request):
            return self.get_response(request)

        sql = statement_timeout_sql(connection, settings.STATEMENT_TIMEOUT)
        if sql is None:
            return self.get_response(request)

        set_sql, reset_sql = sql
        with connection.cursor() as cursor:
            cursor.execute(set_sql)
        try:
            return self.get_response(request)
        finally:
            # connections can outlive the request, and so would the timeout
            try:
                with connection.cursor() as cursor:
                    cursor.execute(reset_sql)
            except DatabaseError:
                # only possible inside a transaction that already failed, and
                # PostgreSQL - the one database where that is possible -
                # undoes the SET when that transaction is rolled back
                logger.warning('Could not reset the statement timeout')

    def process_exception(self, request, exception):
        if not self._applies(request) or not is_statement_timeout(exception):
            return None

        message = (
            'This request took too long. Please retry later, and consider '
            'narrowing it down.'
        )
        if request.path_info.startswith('/api/'):
            response = JsonResponse({'detail': message}, status=503)
        else:
            response = HttpResponse(
                message, status=503, content_type='text/plain'
            )
        response['Retry-After'] = str(STATEMENT_TIMEOUT_RETRY_AFTER)
        return response
