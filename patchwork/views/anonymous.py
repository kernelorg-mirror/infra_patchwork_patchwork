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
from django.shortcuts import render

from patchwork.models import Cover
from patchwork.models import Patch

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
