"""Required release UI tests cannot report a failed Tk start as a skip."""
import configparser
from pathlib import Path
import os
import sys
import unittest
from unittest import mock

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parent/'builder')]
import gui
from gui_test_support import tk_unavailable


class RequiredTkTests(unittest.TestCase):
    def test_pytest_keeps_stream_capture_for_windows_tcl_channels(self):
        config=configparser.ConfigParser()
        config.read(Path(__file__).resolve().parents[2]/'pytest.ini',encoding='utf-8')
        self.assertIn('--capture=sys',config.get('pytest','addopts',fallback='').split(),
            'R368-1: keep --capture=sys; replacing Windows standard handles breaks Tcl file channels')

    def test_optional_startup_failure_is_a_skip(self):
        with mock.patch.dict(os.environ,REQUIRE_BUILDER_TK='0'):
            with self.assertRaises(unittest.SkipTest):tk_unavailable(gui.tk.TclError('missing tk.tcl'))

    def test_required_startup_failure_is_an_assertion(self):
        for message in ('Cannot find a usable tk.tcl','invalid command name tcl_findLibrary'):
            with self.subTest(message=message),mock.patch.dict(os.environ,REQUIRE_BUILDER_TK='1'):
                with self.assertRaisesRegex(AssertionError,'Tk startup is required'):
                    tk_unavailable(gui.tk.TclError(message))

    def test_real_gui_setups_cannot_hide_required_startup_failures(self):
        from test_builder import GuiTest
        from test_builder_first_paint import FirstPaintTests
        for case in (GuiTest('test_undertale_theme_and_short_wording'),
                     FirstPaintTests('test_no_settings_is_themed_before_every_page_builds')):
            with self.subTest(case=type(case).__name__),mock.patch.dict(os.environ,REQUIRE_BUILDER_TK='1'), \
                    mock.patch.object(gui.tk,'Tk',side_effect=gui.tk.TclError('synthetic missing tk.tcl')):
                try:
                    try:case.setUp()
                    except unittest.SkipTest as error:self.fail('A required Tk failure became a skip: '+str(error))
                    except AssertionError as error:self.assertIn('Tk startup is required',str(error))
                    else:self.fail('Failed Tk initialization was accepted')
                finally:
                    case.tearDown()
                    case.doCleanups()


if __name__=='__main__':unittest.main()
