# Patchwork - automated patch tracking system
# Copyright (C) 2008 Jeremy Kerr <jk@ozlabs.org>
# Copyright (C) 2017 Stephen Finucane <stephen@that.guru>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import datetime
from datetime import timezone
from email.encoders import encode_7or8bit
from email.header import Header
from email.mime.nonmultipart import MIMENonMultipart
from email.parser import HeaderParser
import email.utils
import functools
import re

from django.conf import settings
from django.http import Http404
from django.utils.cache import patch_cache_control
from django.views.decorators.http import conditional_page

from patchwork.models import CoverComment
from patchwork.models import Patch
from patchwork.models import PatchComment
from patchwork.parser import split_from_header

if settings.ENABLE_REST_API:
    from rest_framework.authtoken.models import Token


def cacheable_download(max_age=None):
    """Let clients and caches revalidate a download rather than refetch it.

    The ETag is computed from the content, so it costs a render but saves
    sending it again. Without a max_age, caches must revalidate every time,
    which is right for anything that changes as replies come in.

    Only anonymous responses are public: the content is the same for
    everyone, but a shared cache must never hand a logged-in user's response
    to someone an instance gates downloads from.
    """

    def decorator(view):
        @functools.wraps(view)
        @conditional_page
        def wrapper(request, *args, **kwargs):
            response = view(request, *args, **kwargs)
            if response.status_code != 200:
                return response

            # patch_cache_control() writes out False values as 'public=False'
            # rather than leaving them out, so pass only what applies
            if request.user.is_authenticated:
                directives = {'private': True}
            else:
                directives = {'public': True}
            if max_age is None:
                directives['no_cache'] = True
            else:
                directives['max_age'] = max_age
            patch_cache_control(response, **directives)
            return response

        return wrapper

    return decorator


class PatchMbox(MIMENonMultipart):
    patch_charset = 'utf-8'

    def __init__(self, _text):
        MIMENonMultipart.__init__(
            self, 'text', 'plain', **{'charset': self.patch_charset}
        )
        self.set_payload(_text.encode(self.patch_charset))
        encode_7or8bit(self)


def _submission_to_mbox(submission):
    """Get an mbox representation of a single submission.

    Handles both Patch and Cover objects.

    Arguments:
        submission: The Patch or Cover object to convert.

    Returns:
        A string for the mbox file.
    """
    is_patch = isinstance(submission, Patch)

    postscript_re = re.compile('^-{2,3} ?$', re.MULTILINE)
    body = ''

    if submission.content:
        body = submission.content.strip() + '\n'

    parts = postscript_re.split(body, 1)
    if len(parts) == 2:
        (body, postscript) = parts
        body = body.strip() + '\n'
        postscript = postscript.rstrip()
    else:
        postscript = ''

    # TODO(stephenfin): Make this use the tags infrastructure
    if is_patch:
        for comment in PatchComment.objects.filter(patch=submission):
            body += comment.patch_responses
    else:
        for comment in CoverComment.objects.filter(cover=submission):
            body += comment.patch_responses

    if postscript:
        body += '---' + postscript + '\n'

    if is_patch and submission.diff:
        body += '\n' + submission.diff

    delta = submission.date - datetime.datetime.fromtimestamp(
        0, tz=timezone.utc
    ).replace(tzinfo=None)
    utc_timestamp = delta.seconds + delta.days * 24 * 3600

    mail = PatchMbox(body)
    mail['X-Patchwork-Submitter'] = email.utils.formataddr(
        (
            str(Header(submission.submitter.name, mail.patch_charset)),
            submission.submitter.email,
        )
    )
    mail['X-Patchwork-Id'] = str(submission.id)
    if is_patch and submission.delegate:
        mail['X-Patchwork-Delegate'] = str(submission.delegate.email)
    mail.set_unixfrom('From patchwork ' + submission.date.ctime())

    orig_headers = HeaderParser().parsestr(str(submission.headers))
    for key, val in orig_headers.items():
        # we set these ourselves
        if key in ['Content-Type', 'Content-Transfer-Encoding']:
            continue
        # we don't save GPG signatures described in RFC1847 [1] so this
        # Content-Type value is invalid
        # [1] https://tools.ietf.org/html/rfc1847
        if key == 'Content-Type' and val == 'multipart/signed':
            continue

        if key == 'From':
            name, addr = split_from_header(val)
            if addr == submission.project.listemail:
                # If From: is the list address (typically DMARC munging), then
                # use the submitter details (which are cleaned up in the
                # parser) in the From: field so that the patch author details
                # are correct when applied with git am.
                mail['X-Patchwork-Original-From'] = val
                val = mail['X-Patchwork-Submitter']

        mail[key] = val

    if 'Date' not in mail:
        mail['Date'] = email.utils.formatdate(utc_timestamp)

    # NOTE(stephenfin) http://stackoverflow.com/a/28584090/613428
    mail = mail.as_bytes(True).decode()

    return mail


patch_to_mbox = _submission_to_mbox
cover_to_mbox = _submission_to_mbox


def bundle_to_mbox(bundle):
    """Get an mbox representation of a bundle.

    Arguments:
        patch: The Bundle object to convert.

    Returns:
        A string for the mbox file.
    """
    return '\n'.join([patch_to_mbox(p) for p in bundle.ordered_patches()])


def series_patch_to_mbox(patch, series_id):
    """Get an mbox representation of a patch with dependencies.

    Arguments:
        patch: The Patch object to convert.
        series_id: The series number to retrieve dependencies from, or
            '*' if using the latest series.

    Returns:
        A string for the mbox file.
    """
    if series_id == '*':
        if not patch.series:
            raise Http404(
                'Patch does not have an associated series. This is '
                'because the patch was processed with an older '
                'version of Patchwork. It is not possible to '
                'provide dependencies for this patch.'
            )
    else:
        try:
            series_id = int(series_id)
        except ValueError:
            raise Http404(
                'Expected integer series value or *. Received: %r' % series_id
            )

        if patch.series.id != series_id:
            raise Http404('Patch does not belong to series %d' % series_id)

    mbox = []

    # get the series-ified patch
    for dep in patch.series.patches.filter(number__lt=patch.number).order_by(
        'number'
    ):
        mbox.append(patch_to_mbox(dep))

    mbox.append(patch_to_mbox(patch))

    return '\n'.join(mbox)


def series_to_mbox(series):
    """Get an mbox representation of an entire series.

    Arguments:
        series: The Series object to convert.

    Returns:
        A string for the mbox file.
    """
    mbox = []

    for patch in series.patches.all().order_by('number'):
        mbox.append(patch_to_mbox(patch))

    return '\n'.join(mbox)


def regenerate_token(user):
    """Generate (or regenerate) user API tokens.

    Arguments:
        user: The User object to generate a token for.
    """
    Token.objects.filter(user=user).delete()
    Token.objects.create(user=user)
