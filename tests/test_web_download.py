"""Browser downloads must read and name the exported file that Python wrote."""

import importlib.util
import asyncio
import base64
import json
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

    def android_context(self, payload):
        import quickjs

        context = quickjs.Context()
        # QuickJS's Python string bridge truncates embedded NULs; JSON carries binary strings intact.
        context.add_callable('__encode_base64', lambda text: base64.b64encode(json.loads(text).encode('latin-1')).decode('ascii'))
        context.eval("var payload = new Uint8Array(" + json.dumps(list(payload)) + ");")
        context.eval(r"""
            globalThis.window = globalThis;
            globalThis.btoa = function(text) { return __encode_base64(JSON.stringify(text)); };
            globalThis.setTimeout = function(callback) { callback(); };
            globalThis.exportName = null;
            globalThis.exportId = null;
            globalThis.chunks = [];
            globalThis.streamClosed = false;
            globalThis.finished = false;
            globalThis.FS = {
                open(path) { return {offset: 0}; },
                read(stream, buffer, offset, length) {
                    var size = Math.min(length, payload.length - stream.offset);
                    buffer.set(payload.subarray(stream.offset, stream.offset + size), offset);
                    stream.offset += size;
                    return size;
                },
                close() { streamClosed = true; },
            };
            globalThis.GD5AndroidFiles = {
                beginExport(id, name) { exportId = id; exportName = name; return true; },
                appendExport(id, encoded) { chunks.push(encoded); return true; },
                finishExport(id) { finished = true; },
                cancelExport(id) { __gd5_download_done(id, 'cancelled', ''); },
            };
        """)
        return context

    @staticmethod
    def drain_jobs(context):
        while context.execute_pending_job():
            pass

    def test_android_export_preserves_binary_chunks_and_waits_for_native_completion(self):
        payload = bytes(range(256)) * 200
        context = self.android_context(payload)
        result = unittest.mock.Mock()
        with patch.object(browser_platform, 'window', GarblingWindow(context), create=True), \
                patch.object(game_platform, 'IS_WEB', True), \
                patch.object(game_platform, '_download_js_defined', False), \
                patch.object(game_platform, 'run_background') as background:
            game_platform.download_file('fixture/\u00d6sterreich \u6b4c.zip', on_result=result)
            self.drain_jobs(context)
            result.assert_not_called()
            self.assertTrue(context.eval('finished && streamClosed'))
            self.assertEqual(context.eval('exportName'), '\u00d6sterreich \u6b4c.zip')
            chunks = json.loads(context.eval('JSON.stringify(chunks)'))
            decoded = [base64.b64decode(chunk) for chunk in chunks]
            self.assertGreater(len(decoded), 1)
            self.assertEqual(b''.join(decoded), payload)
            context.eval("__gd5_download_done(exportId, 'saved', '')")
            asyncio.run(background.call_args.args[0]())
        result.assert_called_once_with('saved', '')
        self.assertEqual(context.eval('Object.keys(__gd5_download_results).length'), 0)

    def test_android_cancellation_and_write_failure_are_reported_after_picker_returns(self):
        for status, error in [('cancelled', ''), ('error', 'Document is read-only')]:
            with self.subTest(status=status):
                context = self.android_context(b'zip payload')
                result = unittest.mock.Mock()
                with patch.object(browser_platform, 'window', GarblingWindow(context), create=True), \
                        patch.object(game_platform, 'IS_WEB', True), \
                        patch.object(game_platform, '_download_js_defined', False), \
                        patch.object(game_platform, 'run_background') as background:
                    game_platform.download_file('save.zip', on_result=result)
                    self.drain_jobs(context)
                    result.assert_not_called()
                    context.eval(f'__gd5_download_done(exportId, {json.dumps(status)}, {json.dumps(error)})')
                    asyncio.run(background.call_args.args[0]())
                result.assert_called_once_with(status, error)

    def test_android_read_failure_closes_stream_and_cancels_staged_export(self):
        context = self.android_context(b'payload')
        context.eval("FS.read = function() { throw new Error('Cannot read export'); }")
        result = unittest.mock.Mock()
        with patch.object(browser_platform, 'window', GarblingWindow(context), create=True), \
                patch.object(game_platform, 'IS_WEB', True), \
                patch.object(game_platform, '_download_js_defined', False):
            game_platform.download_file('save.zip', on_result=result)
        self.assertTrue(context.eval('streamClosed && !finished'))
        self.assertEqual(result.call_args.args[0], 'error')
        self.assertIn('Cannot read export', result.call_args.args[1])

    def test_android_staging_failure_stops_streaming_and_closes_stream(self):
        context = self.android_context(b'payload')
        context.eval("""
            GD5AndroidFiles.appendExport = function(id, encoded) {
                __gd5_download_done(id, 'error', 'No space left');
                return false;
            };
        """)
        result = unittest.mock.Mock()
        with patch.object(browser_platform, 'window', GarblingWindow(context), create=True), \
                patch.object(game_platform, 'IS_WEB', True), \
                patch.object(game_platform, '_download_js_defined', False):
            game_platform.download_file('save.zip', on_result=result)
        result.assert_called_once_with('error', 'No space left')
        self.assertTrue(context.eval('streamClosed && !finished'))


if __name__ == '__main__':
    unittest.main()
