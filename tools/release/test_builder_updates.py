"""Update notices use invented release responses only. Never contact a network service."""
import io
import json
from pathlib import Path
import queue
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / 'builder')]
import updates
import preferences
import products


NETWORK_ATTEMPTS = mock.Mock(side_effect=AssertionError('No network in fixture tests'))


def setUpModule():
    # The external assertion catches even attempts swallowed by the worker's except Exception.
    NETWORK_ATTEMPTS.reset_mock()
    for target, name in ((socket, 'create_connection'), (socket, 'getaddrinfo'),
                         (socket.socket, 'connect'), (updates.urllib.request, 'build_opener')):
        patch = mock.patch.object(target, name, NETWORK_ATTEMPTS)
        patch.start()
        unittest.addModuleCleanup(patch.stop)
    unittest.addModuleCleanup(NETWORK_ATTEMPTS.assert_not_called)


def release(tag, notes='A small fix.', **kw):
    return dict(tag_name=tag, body=notes, draft=False, prerelease='-' in tag, **kw)


class Versions(unittest.TestCase):
    def test_semver_reference_order_and_metadata(self):
        values = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta',
                  '1.0.0-beta.1', '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0', '1.0.1']
        self.assertEqual(sorted(reversed(values), key=updates.version_key), values)
        self.assertEqual(updates.version_key('v1.0.0+build.8'), updates.version_key('1.0.0'))
        for bad in ('1.2', '1.02.3', '1.0.0-beta.01', '1.0.0-', '1.0.0\n', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                updates.version_key(bad)

    def test_beta_checks_include_prereleases_and_stable_does_not(self):
        repo = 'https://github.com/fixture/fixture'
        rows = [release('v1.0.0-beta.2'), release('v1.0.0'), release('v1.1.0-beta.1')]
        self.assertEqual(updates.select_release(rows[:1], '1.0.0-beta.1', repo).version, '1.0.0-beta.2')
        self.assertEqual(updates.select_release(rows, '1.0.0', repo), None)
        self.assertEqual(updates.select_release(rows[:2], '1.0.0-beta.1', repo).version, '1.0.0')

    def test_notes_are_short_plain_text_and_remote_urls_are_ignored(self):
        row = release('v1.0.1', '# Changes\n- Fixed a bug.\x00\n' + 'x' * 900)
        row['html_url'] = 'file:///fixture'
        row['draft'] = True
        repo = 'https://github.com/fixture/fixture'
        self.assertIsNone(updates.select_release([row], '1.0.0', repo))
        row['draft'] = False
        notice = updates.select_release([row], '1.0.0', repo)
        self.assertLessEqual(len(notice.notes), 480)
        self.assertNotIn('\x00', notice.notes)
        self.assertTrue(notice.notes.startswith('Changes\nFixed a bug.'))
        self.assertEqual(notice.url, repo + '/releases/tag/v1.0.1')

    def test_repository_comes_from_selected_contract(self):
        with mock.patch.object(products.release_contract, 'read', return_value={
                'development_source_base': 'https://github.com/fixture/'}):
            self.assertEqual(updates.repository('undertale'), 'https://github.com/fixture/undertale-3ds')
            self.assertEqual(updates.repository('deltarune'), 'https://github.com/fixture/deltarune-3ds')

    def test_markdown_links_emphasis_and_reference_definitions_are_plain_text(self):
        self.assertEqual(updates.short_notes('## Changes\n- **Fixed** [delivery](https://example.invalid/a).\n'
            '*Fast* _checks_, __clear__ `status`, ~~old~~.\n[Guide][help]\n'
            '[help]: https://example.invalid/help'), 'Changes\nFixed delivery.\nFast checks, clear status, old.\nGuide')

    def test_markdown_preserves_identifiers_and_arithmetic(self):
        text = 'Set game_screen=1 and bottom_mode=2. Use 2*3*4 math; **bold**, _clear_, *fixed*.'
        self.assertEqual(updates.short_notes(text),
                         'Set game_screen=1 and bottom_mode=2. Use 2*3*4 math; bold, clear, fixed.')

    def test_adversarial_notes_are_bounded_before_regex_and_finish_under_50ms(self):
        for body in ('`' * 100_000, '[' * 100_000, '*_' * 50_000):
            with self.subTest(prefix=body[:2]):
                started = time.perf_counter()
                result = updates.short_notes(body)
                elapsed = time.perf_counter() - started
                self.assertLess(elapsed, 0.050)
                self.assertEqual(result, updates.short_notes(body[:4096]))
                self.assertLessEqual(len(result), 480)


class Fetch(unittest.TestCase):
    def fetch(self, data=None, error=None, status=200):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = status
        stream = io.BytesIO(data if data is not None else json.dumps([release('v1.0.0-beta.2')]).encode())
        response.read1.side_effect = stream.read
        opener = mock.Mock()
        opener.open.side_effect = error
        opener.open.return_value = response
        with mock.patch.object(updates.urllib.request, 'build_opener', return_value=opener) as factory:
            result = updates.fetch_latest('https://github.com/fixture/fixture', '1.0.0-beta.1')
        return result, opener, factory

    def test_one_bounded_anonymous_get(self):
        result, opener, factory = self.fetch()
        self.assertEqual(result.notice.version, '1.0.0-beta.2')
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/fixture/fixture/releases?per_page=10')
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(set(k.lower() for k in request.headers), {'accept', 'user-agent'})
        self.assertEqual(opener.open.call_args.kwargs, {'timeout': 3.0})
        self.assertEqual(factory.call_args.args[0].proxies, {})
        self.assertIsInstance(factory.call_args.args[1], updates.NoRedirect)

    def test_documented_release_fields_and_six_assets_fit_the_cap(self):
        # Invented API fixture, including the repeated author/uploader fields and companion hashes.
        user = dict(login='fixture-builder', id=12345678, node_id='MDQ6VXNlcjEyMzQ1Njc4',
                    gravatar_id='', type='User', user_view_type='public', site_admin=False)
        for key, suffix in (('avatar_url', '.png'), ('url', ''), ('html_url', ''),
                            ('followers_url', '/followers'), ('following_url', '/following{/other_user}'),
                            ('gists_url', '/gists{/gist_id}'), ('starred_url', '/starred{/owner}{/repo}'),
                            ('subscriptions_url', '/subscriptions'), ('organizations_url', '/orgs'),
                            ('repos_url', '/repos'), ('events_url', '/events{/privacy}'),
                            ('received_events_url', '/received_events')):
            user[key] = 'https://api.github.com/users/fixture-builder' + suffix
        rows = []
        for index in range(10):
            tag = 'v1.0.0-beta.%d' % (index + 2)
            row = release(tag, ('## Changes\n- **Fixed** [delivery](https://example.invalid/fix).\n' * 25))
            row.update(url='https://api.github.com/repos/fixture/fixture/releases/12345678',
                       assets_url='https://api.github.com/repos/fixture/fixture/releases/12345678/assets',
                       upload_url='https://uploads.github.com/repos/fixture/fixture/releases/12345678/assets{?name,label}',
                       html_url='https://github.com/fixture/fixture/releases/tag/' + tag,
                       id=12345678, author=user, node_id='RE_kwDOABCDEFGHIJKLMN', target_commitish='main',
                       name='Builder ' + tag, immutable=False, created_at='2026-10-20T14:00:00Z',
                       updated_at='2026-10-20T15:00:00Z', published_at='2026-10-20T15:00:00Z',
                       tarball_url='https://api.github.com/repos/fixture/fixture/tarball/' + tag,
                       zipball_url='https://api.github.com/repos/fixture/fixture/zipball/' + tag,
                       discussion_url='https://github.com/fixture/fixture/discussions/123',
                       reactions=dict(url='https://api.github.com/repos/fixture/fixture/releases/123/reactions',
                                      total_count=3, confused=0, heart=1, hooray=2, laugh=0, eyes=0, rocket=0),
                       assets=[])
            for platform in ('windows.zip', 'linux.tar.gz', 'macos.zip'):
                for suffix in ('', '.sha256'):
                    name = 'fixture-3ds-builder-1.0.0-beta.11-' + platform + suffix
                    row['assets'].append(dict(url='https://api.github.com/repos/fixture/fixture/releases/assets/12345678',
                        id=12345678, node_id='RA_kwDOABCDEFGHIJKLMN', name=name, label=name, uploader=user,
                        content_type='application/octet-stream', state='uploaded', size=51000000,
                        digest='sha256:' + 'a' * 64, download_count=1234,
                        created_at='2026-10-20T14:00:00Z', updated_at='2026-10-20T15:00:00Z',
                        browser_download_url='https://github.com/fixture/fixture/releases/download/' + tag + '/' + name))
            rows.append(row)
        data = json.dumps(rows).encode()
        self.assertGreater(len(data), 128 * 1024)
        self.assertLess(len(data), updates.MAX_BYTES)
        self.assertGreater(len(data) * 3, updates.MAX_BYTES)
        result, _, _ = self.fetch(data=data)
        self.assertEqual(result.notice.version, '1.0.0-beta.11')

    def test_success_without_a_new_version_is_distinct_from_failure(self):
        result, _, _ = self.fetch(data=b'[]')
        self.assertEqual(result, updates.Checked('1.0.0-beta.1'))

    def test_offline_private_rate_limited_and_malformed_are_silent(self):
        for error in (OSError('offline'), TimeoutError('timeout')):
            self.assertIsNone(self.fetch(error=error)[0])
        for status in (404, 403, 429, 500, 302):
            self.assertIsNone(self.fetch(status=status)[0])
        for data in (b'bad json', b'{}', b'null', b'[' + b' ' * updates.MAX_BYTES + b']', b'\xff'):
            self.assertIsNone(self.fetch(data=data)[0])


class Background(unittest.TestCase):
    def test_preference_and_timestamp_survive_other_preference_writes(self):
        with tempfile.TemporaryDirectory() as work:
            preferences.save(work, False, updates=False, update_check=('undertale', 1000))
            preferences.save(work, True)
            self.assertEqual(preferences.load(work), dict(boring=True, updates=False,
                                                         update_checks={'undertale': 1000}))

    def test_manual_during_launch_queues_and_bypasses_cooldown(self):
        with tempfile.TemporaryDirectory() as work:
            pending = queue.Queue()
            started, finish = threading.Event(), threading.Event()
            caller = threading.get_ident()
            write_threads = []
            original_save = preferences.save
            def save(*args, **kwargs):
                write_threads.append(threading.get_ident())
                return original_save(*args, **kwargs)
            def fetch(repo, current):
                started.set()
                self.assertTrue(finish.wait(2))
                return updates.Checked(current, updates.Notice('1.0.1', 'Fix', repo + '/releases/tag/v1.0.1'))
            checker = updates.Checker(work, lambda fn, result: pending.put((fn, result)), fetch=fetch,
                                      clock=lambda: 10000)
            done, manual = mock.Mock(), mock.Mock()
            with mock.patch.object(updates, 'repository', return_value='https://github.com/fixture/fixture'), \
                 mock.patch.object(updates.pipeline, 'release_version', return_value='1.0.0'), \
                 mock.patch.object(preferences, 'save', side_effect=save):
                self.assertTrue(checker.request('undertale', done))
                self.assertTrue(started.wait(2))
                self.assertTrue(checker.request('undertale', manual, manual=True))
                duplicate = mock.Mock()
                for _ in range(50):
                    self.assertTrue(checker.request('undertale', duplicate, manual=True))
                self.assertEqual(len(checker.pending), 1)
                self.assertFalse(checker.request('undertale', done))
                self.assertEqual(preferences.load(work)['update_checks']['undertale'], 10000)
                finish.set()
                fn, result = pending.get(timeout=2)
                fn(result)
                fn, result = pending.get(timeout=2)
                fn(result)
                done.assert_called_once()
                manual.assert_called_once()
                self.assertTrue(checker.request('undertale', manual, manual=True))
                fn, result = pending.get(timeout=2)
                fn(result)
                self.assertEqual(manual.call_count, 2)
                duplicate.assert_not_called()
            self.assertEqual(set(write_threads), {caller})
            self.assertFalse(checker.running)

    def test_disable_during_worker_is_preserved_and_pending_results_are_hidden(self):
        with tempfile.TemporaryDirectory() as work:
            pending, release_worker = queue.Queue(), threading.Event()
            def fetch(repo, current):
                release_worker.wait(2)
                return updates.Checked(current)
            checker = updates.Checker(work, lambda *args: pending.put(args), fetch=fetch)
            done = mock.Mock()
            with mock.patch.object(updates, 'repository', return_value='https://github.com/fixture/fixture'), \
                 mock.patch.object(updates.pipeline, 'release_version', return_value='1.0.0'):
                checker.request('undertale', done)
                preferences.save(work, False, updates=False)
                release_worker.set()
                fn, result = pending.get(timeout=2)
                fn(result)
            done.assert_not_called()
            self.assertFalse(preferences.load(work)['updates'])
            self.assertFalse(checker.request('undertale', done, manual=True))

    def test_future_timestamp_is_stale_and_cached_notice_survives_relaunch(self):
        with tempfile.TemporaryDirectory() as work, \
             mock.patch.object(updates, 'repository', return_value='https://github.com/fixture/fixture'), \
             mock.patch.object(updates.pipeline, 'release_version', return_value='1.0.0'):
            pending = queue.Queue()
            notice = updates.Notice('1.0.1', 'Fix', 'https://github.com/fixture/fixture/releases/tag/v1.0.1')
            preferences.save(work, False, update_check=('undertale', 20000))
            checker = updates.Checker(work, lambda *args: pending.put(args),
                fetch=lambda *args: updates.Checked('1.0.0', notice), clock=lambda: 10000)
            self.assertTrue(checker.request('undertale', mock.Mock()))
            fn, result = pending.get(timeout=2)
            fn(result)
            restored, fetch = mock.Mock(), mock.Mock()
            relaunched = updates.Checker(work, mock.Mock(), fetch=fetch, clock=lambda: 10001)
            self.assertFalse(relaunched.request('undertale', restored))
            restored.assert_called_once_with('undertale', updates.Checked('1.0.0', notice))
            fetch.assert_not_called()
            with mock.patch.object(updates.pipeline, 'release_version', return_value='1.0.1'):
                self.assertIsNone(relaunched.cached('undertale'))
            with mock.patch.object(updates, 'repository', return_value='https://github.com/other/product'):
                self.assertIsNone(relaunched.cached('undertale'))

    def test_worker_exception_is_delivered_as_a_failed_check(self):
        with tempfile.TemporaryDirectory() as work:
            pending, done = queue.Queue(), mock.Mock()
            checker = updates.Checker(work, lambda *args: pending.put(args), fetch=mock.Mock(side_effect=RuntimeError()))
            with mock.patch.object(updates, 'repository', return_value='https://github.com/fixture/fixture'), \
                 mock.patch.object(updates.pipeline, 'release_version', return_value='1.0.0'):
                self.assertTrue(checker.request('undertale', done, manual=True))
                fn, result = pending.get(timeout=2)
                fn(result)
            done.assert_called_once_with('undertale', None)


class Rebuild(unittest.TestCase):
    def test_game_payload_excludes_saves_and_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('data.win', 'chapter1_windows/data.win', 'saves/file0', 'SAVES/file9',
                         'chapter1_windows/saves/file0', 'chapter1_windows/settings.ini', 'legacycfg.ini'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'invented')
            rows = products.sd_files(products.PRODUCTS['deltarune'], folder)
            self.assertEqual(sorted(row[1] for row in rows), ['chapter1_windows/data.win', 'data.win'])


class Gui(unittest.TestCase):
    def test_network_guard_detects_attempt_even_when_worker_swallows_exception(self):
        NETWORK_ATTEMPTS.assert_not_called()
        with tempfile.TemporaryDirectory() as work:
            pending = queue.Queue()
            checker = updates.Checker(work, lambda *args: pending.put(args),
                                      fetch=lambda *args: socket.create_connection(('example.invalid', 443)))
            with mock.patch.object(updates, 'repository', return_value='https://github.com/fixture/fixture'), \
                 mock.patch.object(updates.pipeline, 'release_version', return_value='1.0.0'):
                checker.request('undertale', mock.Mock())
                fn, result = pending.get(timeout=2)
                fn(result)
            self.assertIsNone(result)
            with self.assertRaises(AssertionError):
                NETWORK_ATTEMPTS.assert_not_called()
            NETWORK_ATTEMPTS.reset_mock()  # Only this deliberate negative control may attempt a connection.

    def test_rejected_manual_check_and_game_switch_clear_checking(self):
        import gui
        app = gui.App.__new__(gui.App)
        page = mock.Mock()
        page.check_updates.get.return_value = True
        app.pages, app.state = [page, mock.Mock()], mock.Mock(game='undertale')
        with tempfile.TemporaryDirectory() as work:
            preferences.save(work, False, updates=False)
            app.update_checker = updates.Checker(work, mock.Mock())
            app.check_updates(manual=True)
        page.update_feedback.config.assert_called_with(text="Couldn't check")
        page.update_feedback.config(text='Checking...')
        app.reset('deltarune')
        page.update_feedback.config.assert_called_with(text='')
        app._release_notice('undertale', updates.Checked('1.0.0'), manual=True)
        page.update_feedback.config.assert_called_with(text='')
        page.release_notice.assert_not_called()

    def test_manual_check_always_answers_and_failure_preserves_notice(self):
        import gui
        app = gui.App.__new__(gui.App)
        page = mock.Mock()
        page.check_updates.get.return_value = True
        app.pages, app.state = [page], mock.Mock(game='undertale')
        app.update_checker = mock.Mock()
        app.check_updates(manual=True)
        page.update_feedback.config.assert_called_with(text='Checking...')
        callback = app.update_checker.request.call_args.args[1]
        callback('undertale', updates.Checked('1.0.0-beta.1'))
        page.update_feedback.config.assert_called_with(text='Up to date (v1.0.0-beta.1)')
        callback('undertale', None)
        page.update_feedback.config.assert_called_with(text="Couldn't check")
        page.release_notice.assert_not_called()
        app._release_notice('undertale', None)
        self.assertEqual(page.update_feedback.config.call_count, 3)

    def test_normal_launch_schedules_check_without_running_it_on_tk_thread(self):
        import gui
        root, app = mock.Mock(), mock.Mock()
        app.exit_code = 0
        with mock.patch.object(gui.tk, 'Tk', return_value=root), mock.patch.object(gui, 'App', return_value=app):
            self.assertEqual(gui.run(gui.Options()), 0)
        root.after_idle.assert_called_once_with(app.check_updates)
        app.check_updates.assert_not_called()

    def test_both_looks_show_notice_and_explicit_browser_and_disable_preference(self):
        import gui
        try:
            root = gui.tk.Tk()
        except gui.tk.TclError as exc:
            self.skipTest('Tk display unavailable: %s' % exc)
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as work, \
                 mock.patch.object(gui.discover, 'find_copies', return_value=[]), \
                 mock.patch.object(gui.webbrowser, 'open') as browser:
                for boring in (False, True):
                    with self.subTest(boring=boring):
                        preferences.save(work, boring, updates=True)
                        window = gui.tk.Toplevel(root)
                        window.withdraw()
                        app = gui.App(window, gui.Options(game='undertale', work=work, boring=boring))
                        app.update_checker = mock.Mock()
                        page = app.pages[0]
                        notice = updates.Notice('1.0.0-beta.2', 'Fixed an issue.',
                                                'https://github.com/fixture/fixture/releases/tag/v1.0.0-beta.2')
                        app._release_notice('deltarune', updates.Checked('1.0.0-beta.1', notice))
                        self.assertIsNone(page.release_url)
                        app._release_notice('undertale', updates.Checked('1.0.0-beta.1', notice))
                        self.assertIn('v1.0.0-beta.2 is out', page.update_status.cget('text'))
                        app._release_notice('undertale', None, manual=True)
                        self.assertEqual(page.update_feedback.cget('text'), "Couldn't check")
                        self.assertEqual(page.release_url, notice.url)
                        self.assertIn('v1.0.0-beta.2 is out', page.update_status.cget('text'))
                        page.release_notice(None)
                        self.assertEqual(page.release_url, notice.url)
                        with mock.patch.object(updates, 'repository', side_effect=ValueError('Broken contract')), \
                             mock.patch.object(gui.messagebox, 'showinfo') as about:
                            app.about()
                            self.assertNotIn('github.com', about.call_args.args[1])
                        browser.assert_not_called()
                        page.open_release()
                        browser.assert_called_once_with(notice.url)
                        browser.reset_mock()
                        page.check_updates.set(False)
                        page.update_preference()
                        self.assertFalse(preferences.load(work)['updates'])
                        self.assertTrue(page.update_button.instate(['disabled']))
                        self.assertIsNone(page.release_url)
                        page.open_release()
                        browser.assert_not_called()
                        for token in window.tk.call('after', 'info'):
                            window.after_cancel(token)
                        window.destroy()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
