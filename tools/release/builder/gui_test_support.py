"""Tk startup policy for optional developer tests and required release UI gates."""
import os
import unittest


def tk_unavailable(error):
    message='Tk display unavailable: '+str(error)
    if os.environ.get('REQUIRE_BUILDER_TK')=='1':
        raise AssertionError('Tk startup is required for this release gate. '+message) from error
    raise unittest.SkipTest(message) from error
