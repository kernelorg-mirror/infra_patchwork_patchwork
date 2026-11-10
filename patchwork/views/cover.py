# Patchwork - automated patch tracking system
# Copyright (C) 2016 Intel Corporation
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.contrib.auth.decorators import login_not_required
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse

from patchwork.models import Cover
from patchwork.models import Patch
from patchwork.models import Project
from patchwork.views.anonymous import cover_metadata
from patchwork.views.anonymous import is_gated
from patchwork.views.anonymous import render_stub
from patchwork.views.utils import cacheable_download
from patchwork.views.utils import cover_to_mbox


@login_not_required
def cover_detail(request, project_id, msgid):
    project = get_object_or_404(Project, linkname=project_id)
    db_msgid = '<%s>' % msgid

    covers = Cover.objects.filter(project_id=project.id, msgid=db_msgid)
    gated = is_gated(request)
    if gated:
        # keep the large text fields out of a view that cannot render them
        covers = cover_metadata(covers)

    # redirect to patches where necessary
    try:
        cover = covers.get()
    except Cover.DoesNotExist:
        patches = Patch.objects.filter(
            project_id=project.id,
            msgid=db_msgid,
        )
        if patches:
            return HttpResponseRedirect(
                reverse(
                    'patch-detail',
                    kwargs={'project_id': project.linkname, 'msgid': msgid},
                )
            )
        raise Http404('Cover letter does not exist')

    if gated:
        return render_stub(request, cover)

    context = {
        'submission': cover,
        'project': cover.project,
    }

    comments = cover.comments.all()
    comments = comments.select_related('submitter')
    comments = comments.only('submitter', 'date', 'id', 'content', 'cover')
    context['comments'] = comments

    return render(request, 'patchwork/submission.html', context)


@login_not_required
@cacheable_download()
def cover_mbox(request, project_id, msgid):
    db_msgid = '<%s>' % msgid
    project = get_object_or_404(Project, linkname=project_id)
    cover = get_object_or_404(Cover, project_id=project.id, msgid=db_msgid)

    response = HttpResponse(content_type='text/plain')
    response.write(cover_to_mbox(cover))
    response['Content-Disposition'] = 'attachment; filename=%s.mbox' % (
        cover.filename
    )

    return response


def cover_by_id(request, cover_id):
    cover = get_object_or_404(Cover, id=cover_id)

    url = reverse(
        'cover-detail',
        kwargs={
            'project_id': cover.project.linkname,
            'msgid': cover.encoded_msgid,
        },
    )

    return HttpResponseRedirect(url)


@login_not_required
def cover_mbox_by_id(request, cover_id):
    cover = get_object_or_404(Cover, id=cover_id)

    url = reverse(
        'cover-mbox',
        kwargs={
            'project_id': cover.project.linkname,
            'msgid': cover.encoded_msgid,
        },
    )

    return HttpResponseRedirect(url)
