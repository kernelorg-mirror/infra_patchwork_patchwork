# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Helpers for the limited views served to anonymous users.

When ``GATE_ANONYMOUS_ACCESS`` is enabled, anonymous users are shown metadata
only - state, delegate, submitter, series position - and are pointed at the
mailing list archive for the message contents and any discussion. Nothing is
removed, it is only gated behind a login.

The projections here are shared with the message ID lookup view so that every
limited view agrees on what "metadata only" means, and so that the query
budgets asserted in the tests cover all of them.
"""

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.db.models import Count
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import render

from patchwork.models import Cover
from patchwork.models import Patch
from patchwork.models import Series

# Notably absent: content, diff and headers. Those are large text fields and a
# limited view never renders them.
_COMMON_FIELDS = (
    'msgid',
    'name',
    'date',
    'project__linkname',
    'project__name',
    'project__list_archive_url_format',
    'submitter__name',
    'submitter__email',
    'series__total',
)


def is_gated(request):
    """Whether this request only gets the limited anonymous views."""
    return settings.GATE_ANONYMOUS_ACCESS and not request.user.is_authenticated


def patch_metadata(queryset=None):
    """Restrict a Patch queryset to the metadata a limited view renders."""
    if queryset is None:
        queryset = Patch.objects.all()

    return queryset.select_related(
        'project', 'state', 'delegate', 'submitter', 'series'
    ).only(
        *_COMMON_FIELDS,
        'number',
        'archived',
        'state__name',
        'delegate__username',
    )


def cover_metadata(queryset=None):
    """Restrict a Cover queryset to the metadata a limited view renders."""
    if queryset is None:
        queryset = Cover.objects.all()

    return queryset.select_related('project', 'submitter', 'series').only(
        *_COMMON_FIELDS
    )


def render_stub(request, submission):
    """Render the metadata-only view of a patch or cover letter."""
    return render(
        request,
        'patchwork/submission-stub.html',
        {
            'submission': submission,
            'project': submission.project,
        },
    )


def _render_series_list(request, project):
    """Render the limited listing for a project.

    Two bounded queries, and nothing per row. Deliberately not an annotation
    over the patches join: that multiplies rows, and 'Count(distinct=True)'
    over a multi-valued relation does not mean the same thing on PostgreSQL
    as it does on MySQL.
    """
    series_list = list(
        Series.objects.filter(
            project=project, patch__state__action_required=True
        )
        .distinct()
        .select_related('submitter')
        .order_by('-date')[: settings.ANONYMOUS_LIST_MAX_SERIES]
    )

    # roll each series up to a single state, over just the series we are
    # about to render. Django resolves an empty '__in' without going to the
    # database, so an empty project costs one query, not two.
    states = {}
    received = {}
    for row in (
        Patch.objects.filter(series__in=series_list)
        .values('series_id', 'state__name')
        .annotate(count=Count('id'))
    ):
        states.setdefault(row['series_id'], set()).add(row['state__name'])
        received[row['series_id']] = (
            received.get(row['series_id'], 0) + row['count']
        )

    rows = []
    for series in series_list:
        names = states.get(series.id, set())
        rows.append(
            {
                'series': series,
                # None means the patches disagree, which the template renders
                # as "Mixed". The filter above guarantees at least one patch,
                # so an empty set cannot happen.
                'state': next(iter(names)) if len(names) == 1 else None,
                'received': received.get(series.id, 0),
            }
        )

    return render(
        request,
        'patchwork/anonymous-list.html',
        {
            'project': project,
            'rows': rows,
            'max_series': settings.ANONYMOUS_LIST_MAX_SERIES,
            'staleness': settings.ANONYMOUS_LIST_CACHE_TIMEOUT // 60,
        },
    )


def series_list(request, project):
    """Serve the limited, cacheable listing for a project.

    The listing has no filtering, ordering or pagination, so there is exactly
    one URL per project and exactly one cache entry per project - at every
    layer, ours and any shared cache in front of us. That bounded key space
    is the entire point: the full patch list multiplies out to an unbounded
    number of distinct URLs, which no cache can help with.
    """
    if request.META.get('QUERY_STRING'):
        # Drop it rather than ignore it, so that junk parameters cannot turn
        # into cache entries. 'no-store' keeps a shared cache from filling up
        # with one redirect object per parameter a crawler invents.
        response = HttpResponseRedirect(request.path)
        response['Cache-Control'] = 'no-store'
        return response

    if len(messages.get_messages(request)):
        # This request has user-specific chrome to render, which must never
        # reach a shared cache. Checking before the lookup also means their
        # messages are not swallowed by a cache hit: we never iterate the
        # storage, so nothing is marked as read.
        response = _render_series_list(request, project)
        response['Cache-Control'] = 'no-store'
        return response

    # keyed on the project id, not the linkname: linknames run to 255
    # characters, and memcached keys stop at 250
    key = 'anon-series-list:%d' % project.id
    body = cache.get(key)
    if body is None:
        body = _render_series_list(request, project).content
        cache.set(key, body, settings.ANONYMOUS_LIST_CACHE_TIMEOUT)

    response = HttpResponse(body)
    response['Cache-Control'] = 'public, max-age=%d' % (
        settings.ANONYMOUS_LIST_CACHE_TIMEOUT
    )

    return response
