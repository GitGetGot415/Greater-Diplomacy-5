import asyncio
import importlib.util
import platform as browser_platform
import unittest
from unittest import mock

from data import platform as game_platform
from screens.menus import menu
from tests.web_fixtures import GarblingWindow


class MenuVersionTests(unittest.TestCase):
    def version_status(self, current, released):
        with mock.patch.object(menu.c, "GAME_VERSION", current), \
                mock.patch.object(menu.urllib.request, "urlopen") as open_url:
            open_url.return_value.read.return_value = released.encode("utf-8")
            instance = menu.Menu.__new__(menu.Menu)
            instance.check_version()
        self.assertIn(current, instance.version_status)
        return instance.version_status.replace(current, "{current}").replace(released, "{released}")

    def test_version_status_compares_version_numbers(self):
        # Equal comparisons must report the same state after display text changes.
        states = {"newer": self.version_status("v2", "v1"),
                  "older": self.version_status("v1", "v2"),
                  "same": self.version_status("v1", "v1"),
                  "error": self.version_status("v1", "invalid")}
        self.assertEqual(len(set(states.values())), len(states))
        cases = (
            ("v47", "v46", "newer"),
            ("v9", "v10", "older"),
            ("v10", "v9", "newer"),
            ("v47", "v47", "same"),
            ("v47", "invalid", "error"),
            ("invalid", "v47", "error"),
        )
        for current, released, state in cases:
            with self.subTest(current=current, released=released):
                self.assertEqual(self.version_status(current, released), states[state])


class WebMenuVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_uses_the_desktop_version_comparison(self):
        for current, released in (("v9", "v10"), ("v10", "v9"), ("v10", "v10"),
                                  ("v10", "invalid")):
            with self.subTest(current=current, released=released), \
                    mock.patch.object(menu.c, "GAME_VERSION", current), \
                    mock.patch.object(menu.urllib.request, "urlopen") as open_url, \
                    mock.patch.object(menu, "browser_fetch_text", new_callable=mock.AsyncMock) as fetch:
                open_url.return_value.read.return_value = released.encode("utf-8")
                fetch.return_value = (200, released + "\n")
                desktop = menu.Menu.__new__(menu.Menu)
                desktop.check_version()
                browser = menu.Menu.__new__(menu.Menu)
                await browser.check_version_web()
                self.assertEqual(browser.version_status, desktop.version_status)
                fetch.assert_awaited_once_with(
                    menu.MENU_VERSION_API_URL, headers={"Accept": menu.MENU_VERSION_ACCEPT})

    async def test_rate_limits_fall_back_to_the_public_version_file(self):
        for status in (403, 429):
            with self.subTest(status=status), \
                    mock.patch.object(menu, "browser_fetch_text", new_callable=mock.AsyncMock) as fetch:
                fetch.side_effect = [(status, "rate limited"), (200, menu.c.GAME_VERSION)]
                instance = menu.Menu.__new__(menu.Menu)
                await instance.check_version_web()
                self.assertEqual(fetch.await_count, 2)
                self.assertTrue(fetch.await_args_list[1].args[0].startswith(menu.c.VERSION_CHECK_URL + "?t="))
                expected = menu.Menu.__new__(menu.Menu)
                expected._set_version_status(menu.c.GAME_VERSION)
                self.assertEqual(instance.version_status, expected.version_status)

    async def test_failed_requests_finish_and_allow_refresh(self):
        for failure in (OSError("offline"), TimeoutError(), (500, "server error")):
            with self.subTest(failure=failure), \
                    mock.patch.object(menu, "IS_WEB", True), \
                    mock.patch.object(menu, "browser_fetch_text", new_callable=mock.AsyncMock) as fetch, \
                    mock.patch.object(menu, "run_background") as background:
                if isinstance(failure, Exception):
                    fetch.side_effect = failure
                else:
                    fetch.return_value = failure
                instance = menu.Menu.__new__(menu.Menu)
                instance.version_status = "Checking version..."
                await instance.check_version_web()
                self.assertNotEqual(instance.version_status, "Checking version...")
                self.assertIn(menu.c.GAME_VERSION, instance.version_status)
                instance.trigger_version_check()
                background.assert_called_once_with(instance.check_version_web)

    async def test_refresh_schedules_one_browser_task_and_no_thread(self):
        instance = menu.Menu.__new__(menu.Menu)
        instance.version_status = ""
        with mock.patch.object(menu, "IS_WEB", True), \
                mock.patch.object(game_platform, "IS_WEB", True), \
                mock.patch.object(menu, "run_background", wraps=game_platform.run_background) as background, \
                mock.patch.object(menu, "browser_fetch_text", new_callable=mock.AsyncMock) as fetch, \
                mock.patch.object(menu.threading, "Thread") as thread:
            fetch.return_value = (200, menu.c.GAME_VERSION)
            instance.trigger_version_check()
            instance.trigger_version_check()
            background.assert_called_once_with(instance.check_version_web)
            thread.assert_not_called()
            await asyncio.sleep(0)
            fetch.assert_awaited_once()
            self.assertNotEqual(instance.version_status, "Checking version...")


class FetchWindow(GarblingWindow):
    def eval(self, source):
        result = super().eval(source)
        while self._context.execute_pending_job():
            pass
        return result


@unittest.skipUnless(importlib.util.find_spec("quickjs"), "QuickJS is not installed")
class BrowserFetchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import quickjs  # Optional engine, imported after the availability check.

        self.context = quickjs.Context()
        self.context.eval("""
            globalThis.window = globalThis;
            globalThis.aborted = 0;
            globalThis.AbortController = class {
                constructor() { this.signal = {}; }
                abort() { aborted++; }
            };
            globalThis.fetch = function(url, options) {
                globalThis.request = {url, options};
                return Promise.resolve({status: 200, text: () => Promise.resolve('v10')});
            };
        """)
        self.window_patch = mock.patch.object(
            browser_platform, "window", FetchWindow(self.context), create=True)
        self.window_patch.start()
        self.addCleanup(self.window_patch.stop)

    def assert_request_cleaned_up(self):
        self.assertEqual(self.context.eval(
            "Object.keys(window).filter(key => key.startsWith('__gd5_fetch_')).length"), 0)
        self.assertEqual(self.context.eval("aborted"), 1)

    async def test_fetch_runs_javascript_and_returns_the_response_body(self):
        result = await game_platform.browser_fetch_text(
            menu.MENU_VERSION_API_URL, headers={"Accept": menu.MENU_VERSION_ACCEPT})
        self.assertEqual(result, (200, "v10"))
        self.assertEqual(self.context.eval("request.url"), menu.MENU_VERSION_API_URL)
        self.assertEqual(self.context.eval("request.options.headers.Accept"), menu.MENU_VERSION_ACCEPT)
        self.assertEqual(self.context.eval("request.options.cache"), "no-store")
        self.assert_request_cleaned_up()

    async def test_http_errors_are_returned_for_rate_limit_handling(self):
        self.context.eval("fetch = () => Promise.resolve({status: 429, text: () => Promise.resolve('limit')})")
        self.assertEqual(await game_platform.browser_fetch_text(menu.MENU_VERSION_API_URL), (429, "limit"))
        self.assert_request_cleaned_up()

    async def test_network_rejection_is_reported(self):
        self.context.eval("fetch = () => Promise.reject(new TypeError('offline'))")
        with self.assertRaises(OSError):
            await game_platform.browser_fetch_text(menu.MENU_VERSION_API_URL)
        self.assert_request_cleaned_up()

    async def test_timeout_aborts_the_request_and_removes_its_state(self):
        self.context.eval("fetch = () => new Promise(() => {})")
        with self.assertRaises(TimeoutError):
            await game_platform.browser_fetch_text(menu.MENU_VERSION_API_URL, timeout=0.01)
        self.assert_request_cleaned_up()

    async def test_cancellation_aborts_the_request_and_removes_its_state(self):
        self.context.eval("fetch = () => new Promise(() => {})")
        task = asyncio.create_task(game_platform.browser_fetch_text(menu.MENU_VERSION_API_URL))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_request_cleaned_up()


if __name__ == "__main__":
    unittest.main()
