# Patchwork - automated patch tracking system
# Copyright (C) 2017 Stephen Finucane <stephen@that.guru>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse

from patchwork.models import Series
from patchwork.views.anonymous import is_gated
from patchwork.views.anonymous import patch_metadata
from patchwork.views.utils import series_to_mbox


@login_not_required
def series_detail(request, series_id):
    series = get_object_or_404(
        Series.objects.select_related(
            'project', 'submitter', 'cover_letter', 'cover_letter__project'
        ),
        id=series_id,
    )

    gated = is_gated(request)

    if (
        not gated
        and series.project
        and series.project.is_editable(request.user)
    ):
        # This read-only summary has no bulk-edit UI (state, delegate,
        # archive, bundles), unlike the patch list it replaced as
        # Series.get_absolute_url(). Maintainers get sent to the filtered
        # patch list instead, where that's still available; everyone else
        # gets the cheaper page, since they couldn't edit anything anyway.
        return HttpResponseRedirect(
            reverse(
                'patch-list',
                kwargs={'project_id': series.project.linkname},
            )
            + '?series=%d' % series.id
        )

    patches = series.patches.order_by('number')
    if gated:
        patches = patch_metadata(patches)
    else:
        patches = (
            patches.select_related('state', 'submitter', 'delegate')
            .defer('content', 'diff', 'headers')
            .prefetch_related('check_set')
        )

    context = {
        'series': series,
        'project': series.project,
        'patches': patches,
        'gated': gated,
    }
    if not gated:
        context['dependencies'] = series.dependencies.all()

    return render(request, 'patchwork/series.html', context)


@login_not_required
def series_mbox(request, series_id):
    series = get_object_or_404(Series, id=series_id)

    response = HttpResponse(content_type='text/plain')
    response.write(series_to_mbox(series))
    response['Content-Disposition'] = 'attachment; filename=%s.patch' % (
        series.filename
    )

    return response
