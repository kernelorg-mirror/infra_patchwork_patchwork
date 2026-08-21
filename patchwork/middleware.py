# Patchwork - automated patch tracking system
# Copyright (C) 2026 Konstantin Ryabitsev <konstantin@linuxfoundation.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

from django.conf import settings
from django.contrib.auth.middleware import LoginRequiredMiddleware


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
