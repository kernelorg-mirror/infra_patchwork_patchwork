# Patchwork - automated patch tracking system
# Copyright (C) 2008 Jeremy Kerr <jk@ozlabs.org>
# Copyright (C) 2016 Stephen Finucane <stephen@that.guru>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import render
from django.urls import reverse


@login_not_required
def about(request):
    context = {
        'enabled_apis': {
            'rest': settings.ENABLE_REST_API,
            'xmlrpc': settings.ENABLE_XMLRPC,
        },
        'admins': () if settings.ADMINS_HIDE else settings.ADMINS,
    }

    return render(request, 'patchwork/about.html', context)


@login_not_required
def redirect(request):
    """Redirect for legacy URLs.

    Remove this when Patchwork 3.0 is released.
    """
    return HttpResponsePermanentRedirect(reverse('about'))
