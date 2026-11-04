"""Optional, anonymous release notices. No downloads, credentials, retries or build dependency."""
from __future__ import annotations

import dataclasses
import http.client
import json
import re
import threading
import time
import urllib.parse
import urllib.request

import pipeline
import preferences
import products

TIMEOUT = 3.0
MAX_BYTES = 256 * 1024
AUTO_INTERVAL = 15 * 60
RELEASE_LIMIT = 10
NOTES_INPUT_LIMIT = 4096
SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
                    r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
                    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?')


def version_key(text):
    """SemVer 2 precedence, including numeric prerelease identifiers; metadata is ignored."""
    if not isinstance(text, str) or len(text) > 160:
        raise ValueError('Invalid release version')
    match = SEMVER.fullmatch(text.removeprefix('v'))
    if not match:
        raise ValueError('Invalid release version')
    parts = []
    for part in (match[4] or '').split('.') if match[4] else ():
        if part.isdigit():
            if len(part) > 1 and part.startswith('0'):
                raise ValueError('Leading zero in prerelease')
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(int(match[i]) for i in (1, 2, 3)) + (not bool(match[4]), tuple(parts))


def repository(game, root=pipeline.SOURCE_ROOT):
    """Use the selected tree's release contract, just as its source branding does."""
    contract = products.release_contract.read(root)
    url = contract['development_source_base'].rstrip('/') + '/' + products.PRODUCTS[game].app_name
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', parsed.path)):
        raise ValueError('Invalid release repository')
    return url


@dataclasses.dataclass(frozen=True)
class Notice:
    version: str
    notes: str
    url: str


@dataclasses.dataclass(frozen=True)
class Checked:
    current: str
    notice: Notice | None = None


def short_notes(body):
    if not isinstance(body, str):
        raise ValueError('Invalid release notes')
    # Display as plain text; do not interpret remote HTML, links or terminal controls.
    text = ''.join(c for c in body[:NOTES_INPUT_LIMIT] if c in '\n\t' or c.isprintable())
    text = re.sub(r'!?\[([^\[\]\n]+)\]\([^\n)]*\)', r'\1', text)
    text = re.sub(r'!?\[([^\[\]\n]+)\]\[[^\[\]\n]*\]', r'\1', text)
    text = re.sub(r'^\s*\[[^\[\]\n]+\]:.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(?<!`)(`{1,3})(?!`)(.+?)(?<!`)\1(?!`)', r'\2', text)
    text = re.sub(r'(?<!\w)(\*{1,3}|_{1,3}|~~)(?=\S)(.+?)(?<=\S)\1(?!\w)', r'\2', text)
    lines = [re.sub(r'^\s*[#*>-]+\s*', '', line).strip() for line in text.splitlines()]
    return '\n'.join(line for line in lines if line)[:480]


def select_release(rows, current, repo):
    if not isinstance(rows, list) or len(rows) > RELEASE_LIMIT:
        raise ValueError('Invalid releases response')
    current_key = version_key(current)
    best = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid release')
        if row.get('draft') is not False or type(row.get('prerelease')) is not bool:
            continue
        try:
            tag = row['tag_name']
            key = version_key(tag)
            if key <= current_key or (current_key[3] and (not key[3] or row['prerelease'])):
                continue
            # Reconstruct the page from the trusted repository and validated tag, never a remote URL.
            notice = Notice(tag.removeprefix('v'), short_notes(row.get('body') or ''),
                            repo + '/releases/tag/' + urllib.parse.quote(tag, safe=''))
        except (ValueError, KeyError, TypeError):
            continue
        if best is None or key > best[0]:
            best = key, notice
    return best[1] if best else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_latest(repo, current):
    """One plain GET. Socket timeout, total read deadline and bounded response; errors are silent."""
    try:
        path = urllib.parse.urlsplit(repo).path
        if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            return None
        request = urllib.request.Request('https://api.github.com/repos' + path + '/releases?per_page=10',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': '3DS-builder'}, method='GET')
        # No cookies, auth handlers or environment proxy credentials. A redirect is a failed check.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        deadline = time.monotonic() + TIMEOUT
        with opener.open(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return None
            data = bytearray()
            while len(data) <= MAX_BYTES and time.monotonic() < deadline:
                block = response.read1(min(16384, MAX_BYTES + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
            else:
                return None
        if time.monotonic() >= deadline or len(data) > MAX_BYTES:
            return None
        return Checked(current, select_release(json.loads(data), current, repo))
    except (OSError, ValueError, TypeError, KeyError, RecursionError, http.client.HTTPException):
        return None


class Checker:
    """A single daemon worker; the UI never waits or joins it, even when DNS is slow."""
    def __init__(self, work, dispatch, fetch=None, clock=time.time):
        self.work, self.dispatch = work, dispatch
        self.fetch, self.clock = fetch or fetch_latest, clock
        self.running = False
        self.pending = []

    def cached(self, game):
        """Restore only a newer notice with a tag URL belonging to today's configured repository."""
        try:
            data = preferences.load(self.work).get('update_notices', {}).get(game)
            if not data:
                return None
            repo = repository(game)
            tag = data['url'].removeprefix(repo + '/releases/tag/')
            tag = urllib.parse.unquote(tag)
            if (data['url'] != repo + '/releases/tag/' + urllib.parse.quote(tag, safe='')
                    or tag.removeprefix('v') != data['version']
                    or version_key(tag) <= version_key(pipeline.release_version())):
                return None
            return Notice(data['version'], short_notes(data['notes']), data['url'])
        except (KeyError, TypeError, ValueError, OSError, pipeline.BuildFailed):
            return None

    def request(self, game, done, manual=False):
        prefs = preferences.load(self.work)
        if not prefs.get('updates', True):
            return False
        if self.running:
            if manual and not any(queued_game == game for queued_game, _ in self.pending):
                self.pending.append((game, done))
            return manual
        now = self.clock()
        last = prefs.get('update_checks', {}).get(game)
        if not manual:
            notice = self.cached(game)
            if notice:
                done(game, Checked(pipeline.release_version(), notice))
        if not manual and last is not None and 0 <= now - last < AUTO_INTERVAL:
            return False
        # All preference writes run on the caller's Tk thread, including failed attempts.
        preferences.save(self.work, prefs['boring'], update_check=(game, now))
        self.running = True

        def run():
            result = None
            try:
                repo = repository(game)
                current = pipeline.release_version()
                result = self.fetch(repo, current)
            except Exception:
                pass  # Optional notices cannot become a wizard error or a build dependency.
            self.dispatch(finish, result)

        def finish(result):
            self.running = False
            latest = preferences.load(self.work)
            if latest.get('updates', True):
                if result and result.notice:
                    preferences.save(self.work, latest['boring'],
                                     update_notice=(game, dataclasses.asdict(result.notice)))
                done(game, result)
            if self.pending:
                next_game, next_done = self.pending.pop(0)
                self.request(next_game, next_done, manual=True)

        threading.Thread(target=run, daemon=True, name='release-check').start()
        return True
