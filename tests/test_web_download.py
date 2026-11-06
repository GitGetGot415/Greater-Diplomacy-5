"""Browser downloads must read and name the exported file that Python wrote."""

import importlib.util
import os
import platform as browser_platform  # pygbag adds .window to the stdlib module
import unittest
from unittest.mock import patch

from data import platform as game_platform
from tests.web_fixtures import GarblingWindow


@unittest.skipUnless(importlib.util.find_spec('quickjs'), 'QuickJS is not installed')
class WebDownloadTests(unittest.TestCase):
    def test_download_keeps_a_non_ascii_export_name_through_pygbag(self):
        import quickjs

        context = quickjs.Context()
        context.eval(r"""
            globalThis.window = globalThis;
            globalThis.readPath = null;
            globalThis.downloadName = null;
            globalThis.FS = {readFile(path) { readPath = path; return new Uint8Array([1]); }};
            globalThis.Blob = class { constructor(parts) { this.parts = parts; } };
            globalThis.URL = {createObjectURL() { return 'blob:export'; }};
            globalThis.document = {
                createElement() { return {click() { downloadName = this.download; }}; },
                body: {appendChild() {}, removeChild() {}},
            };
        """)
        path = os.path.join('exports', 'Österreich-Ungarn 歌_flag.png')
        with patch.object(browser_platform, 'window', GarblingWindow(context), create=True), \
                patch.object(game_platform, 'IS_WEB', True), \
                patch.object(game_platform, '_download_js_defined', False):
            game_platform.download_file(path)

        self.assertEqual(context.eval('readPath'), path)
        self.assertEqual(context.eval('downloadName'), os.path.basename(path))


if __name__ == '__main__':
    unittest.main()
