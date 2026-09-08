# Patchwork - automated patch tracking system
# Copyright (C) 2022 Stephen Finucane <stephen@that.guru>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import re
import unittest
from unittest import mock

from patchwork import version

from django import test
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


class TestVersion(test.TestCase):
    @override_settings(PATCHWORK_BUILD_VERSION='korg-2026090801')
    def test_build_version_appended(self):
        self.assertTrue(
            version.get_latest_version().endswith('-korg-2026090801')
        )

    @override_settings(PATCHWORK_BUILD_VERSION='')
    def test_build_version_unset_not_appended(self):
        base_version = version.format_git_version(
            version.get_git_version()
        ) or version.format_str_version(version.get_str_version())

        self.assertEqual(version.get_latest_version(), base_version)

    def test_build_version_settings_not_configured(self):
        """get_build_version() must not blow up when Django isn't set up.

        This happens when the docs are built: 'import patchwork' runs
        get_latest_version() at module load time, with no
        DJANGO_SETTINGS_MODULE in sight.
        """

        class Unconfigured:
            def __getattr__(self, name):
                raise ImproperlyConfigured('settings are not configured')

        with mock.patch('django.conf.settings', Unconfigured()):
            self.assertEqual(version.get_build_version(), '')

    @unittest.skipIf(
        version.get_git_version() == '',
        "this doesn't appear to be a git repo so we can't run git-based tests",
    )
    def test_validate_version(self):
        str_version = version.get_str_version()
        git_version = version.get_git_version()

        str_re = r'v\d\.\d\.\d(([ab]|rc)\d+)?'  # v1.2.3a0
        git_re = r'v\d\.\d\.\d(\.post\d+\+\w+)?'  # v1.2.3.post1+abc123

        str_match = re.match(str_re, version.format_str_version(str_version))
        git_match = re.match(git_re, version.format_git_version(git_version))

        # both should match a specific pattern at a minimum
        self.assertIsNotNone(str_match)
        self.assertIsNotNone(git_match)

        # if the tag is missing from one, it should be missing from the other
        # (and vice versa)
        self.assertEqual(
            bool(str_match.group(1)),
            bool(git_match.group(1)),
            f'mismatch between git and version.txt post-release metadata: '
            f'git={git_match.group(1)!r}, version.txt={str_match.group(1)!r}',
        )
