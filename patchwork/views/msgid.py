# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render

from patchwork.models import Cover
from patchwork.models import Patch
from patchwork.views.anonymous import cover_metadata
from patchwork.views.anonymous import patch_metadata


def _default_archive_url(msgid):
    """Build an archive URL for a msgid we know nothing else about.

    Used when no submission matches, in which case there is no project and
    therefore no 'list_archive_url_format' to work with. Takes a trimmed
    msgid, i.e. one without the enclosing angle brackets.
    """
    if not settings.DEFAULT_ARCHIVE_URL_FORMAT:
        return None

    return settings.DEFAULT_ARCHIVE_URL_FORMAT.format(msgid)


@login_not_required
def msgid_lookup(request, msgid):
    """Look a message ID up across every project.

    Message IDs are only unique within a project. The same series is
    frequently delivered to several lists tracked by the same Patchwork
    instance, and each copy gets its own state and delegate. We therefore
    always render a list, even for a single hit: a URL that redirected today
    but listed tomorrow, because the patch was picked up by a second project
    in the meantime, would be an unpleasant surprise for anyone who had
    bookmarked it.

    Deliberately kept to two indexed lookups. This view is the entry point we
    hand out to people who do not have an account, so the miss path - which is
    also the path automated crawlers take - must stay cheap.
    """
    db_msgid = Patch.decode_msgid(msgid)

    patches = patch_metadata(Patch.objects.filter(msgid=db_msgid))
    covers = cover_metadata(Cover.objects.filter(msgid=db_msgid))

    submissions = [
        {'kind': 'patch', 'submission': patch} for patch in patches
    ] + [{'kind': 'cover letter', 'submission': cover} for cover in covers]
    submissions.sort(key=lambda item: item['submission'].project.name)

    trimmed_msgid = db_msgid.strip('<>')
    context = {
        'msgid': trimmed_msgid,
        'submissions': submissions,
    }
    if not submissions:
        context['archive_url'] = _default_archive_url(trimmed_msgid)

    return render(request, 'patchwork/msgid.html', context)
