# SPDX-License-Identifier: GPL-2.0-or-later

"""Runs the integration tests inside Blender:

    blender -b --factory-startup --python-exit-code 1 --python tests_blender/run.py

The add-on is registered from this checkout, not from the installed extensions.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import io_import_0ad_actor  # noqa: E402

io_import_0ad_actor.register()
suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
