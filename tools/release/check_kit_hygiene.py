#!/usr/bin/env python3
"""Inspect final kit members, nested ZIPs and bytecode without executing them.

Preserve approved credits and system defaults; reject private build paths and
internal attribution. Report locations, never rejected values.
"""
import argparse
import ast
import hashlib
import importlib.util
import io
import json
import marshal
from pathlib import Path, PurePosixPath
import re
import sys
import tokenize
import types
import zipfile


# Each exception has a reviewed purpose; private profile/tree rules always win.
ALLOWED_PATH_PATTERNS = (
    (r'^/(?:usr|bin|sbin|dev|System|Library|etc|var|opt)(?:/|$)', 'Generic Unix OS and SDK defaults.'),
    (r'^[A-Za-z]:[/\\](?:Windows|Program Files(?: \(x86\))?|ProgramData)(?:[/\\]|$)', 'Generic Windows OS defaults.'),
    (r'^[A-Za-z]:[/\\](?:devkitPro|msys64|msys2|mingw64|mingw32)(?:[/\\]|$)', 'Public SDK and compiler installation defaults.'),
    (r'^(?:%[A-Za-z_][A-Za-z0-9_]*%|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)', 'Environment placeholders do not identify a machine.'),
    (r'^<[^>]+>$', 'Neutral bytecode labels such as frozen modules are not filesystem paths.'),
    (r'^[A-Za-z]:[/\\](?:$|u3ds|Steam|GOG Games|Games|PC Games)', 'Generic removable-card, builder and store defaults reveal no private workspace.'),
    (r'^[/\\]{2}[?.][/\\]', 'Windows device and named-pipe namespaces are local OS interfaces, not hosts.'),
    (r'^[/\\]{2}(?:server|host|localhost|example\.invalid)[/\\]', 'Generic protocol examples inside vendor data, never a named private host.'),
)
ALLOWED_CONTEXT_PATTERNS = (
    (r'(?:^|/)runtime/|python314\.zip!|(?:^|/)vendor/', 'Generic third-party and standard-library constants; explicit private markers still fail.'),
    (r'(?:^|/)(?:LICEN[SC]E|NOTICE|THIRD_PARTY_NOTICES)(?:[._-][A-Za-z0-9.-]+)?$', 'Approved notice paths and examples; explicit private markers still fail.'),
    (r'(?:^|/)docs/release/credits-port\.txt$', 'Approved public credit; owner-name exception only.'),
)
REVIEWED_VENDOR_EXAMPLES = (
    ('pydoc_data/topics.py', '748713ad41069b2da5df151e67a9ed010f5f1e7a301c17cf9e5a109e22a75135',
     r'^[/\\]+Users[/\\]+(?:\{name\}|Galahad)(?![A-Za-z0-9_.-])',
     'Unmodified upstream raw-f-string tutorial placeholders, not a build-machine profile.'),
    ('venv/scripts/common/Activate.ps1', '4ebdbe1a812a523c51bec2cf80817936c92798b0fc38b39804360c2d6659ccfb',
     r'^[/\\]+Users[/\\]+MyUser[/\\]+Common[/\\]+\.venv',
     'Unmodified upstream PowerShell activation tutorial, not a build-machine profile.'),
    ('pydoc_data/topics.py', 'e379cd29b03fe1ce012f7261b454d8098b6542d846a66fd732994b7468f6cf48',
     r'^[/\\]+Users[/\\]+(?:\{name\}|Galahad)(?![A-Za-z0-9_.-])',
     'Pinned Mac runtime copy of the upstream raw-f-string tutorial placeholders.'),
    ('venv/scripts/common/Activate.ps1', 'eb8ce20f580877d300c4fed60a7f36daa18715d35c50bb3596d6995d023b4ffe',
     r'^[/\\]+Users[/\\]+MyUser[/\\]+Common[/\\]+\.venv',
     'Pinned Mac runtime copy of the upstream PowerShell activation tutorial.'),
)
OWNER = re.compile(r'(?<![A-Za-z])N?' + 'Eth' + 'an' + r'\b', re.I)
PRIVATE_NAME = 'delta' + 'tale'
PRIVATE_PATHS = (
    ('private-profile-path', r'[/\\](?:Users|home)[/\\][^\s\x00"<>|]+'),
    ('private-workspace-path', r'\b[A-Za-z]:[/\\]+(?:AI|workspace|workspaces|work|projects?|repos?|src|build|bld|checkout|private)[/\\]'),
    ('private-tree-path', r'(?:\.' + 'claude' + r'[/\\]|work' + r'trees[/\\]|scratch[/\\]agents[/\\])'),
)
UNC = re.compile(r'(?<![A-Za-z0-9_/\\%])\\\\[A-Za-z0-9][A-Za-z0-9_.-]*\\[A-Za-z0-9_$.-]+', re.I)
INTERNAL = re.compile(r'\blan' + r'e\s+|\(lan' + r'e\b|\blead\s+ruling\b|\b(?:'
    + 'cla' + 'ude|co' + 'dex|gem' + 'ini|g' + r'pt(?:[ -]?[0-9][\w.-]*)?|(?:op' + 'us|son' + 'net|ar' + 'gon'
    + r')(?=[ \t]+(?:[0-9]|model|agent|high|medium|low)|-[0-9])'
    + r')\b', re.I)


def approved_notice(name):
    path = name.split('!')[-1].replace('\\', '/').removesuffix(' (name)')
    if path.endswith('docs/release/credits-port.txt'):
        return True
    return bool(re.fullmatch(r'(?:LICEN[SC]E|NOTICE|THIRD_PARTY_NOTICES)(?:[._-][A-Za-z0-9.-]+)?',
                             PurePosixPath(path).name, re.I))


def vendor_member(name):
    path = name.replace('\\', '/').lower()
    return bool(re.search(ALLOWED_CONTEXT_PATTERNS[0][0], path, re.I))


def private_path_findings(text, name, approved_profiles=()):
    for rule, expression in PRIVATE_PATHS:
        for match in re.finditer(expression, text, re.I):
            if rule == 'private-profile-path' and any(re.search(p, match.group(), re.I) for p in approved_profiles):
                continue
            yield rule, match.start()
    # A drive letter alone is not private: card roots, published store defaults
    # and anonymous test constants are valid. Workspace markers above are banned.
    for match in UNC.finditer(text):
        if vendor_member(name) and re.search(ALLOWED_PATH_PATTERNS[-1][0], match.group(), re.I):
            continue
        yield 'private-unc-host', match.start()


def comment_spans(name, data):
    """Exact UTF-8 byte spans; variable expressions and Unicode tables are data."""
    if b'\0' in data:
        return []
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return []
    suffix = PurePosixPath(name.split('!')[-1]).suffix.lower()
    ascii_only = text.isascii()
    def byte_offset(index):
        return index if ascii_only else len(text[:index].encode('utf-8'))
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode('utf-8')))
    def at(row, col):
        return offsets[row - 1] + len(lines[row - 1][:col].encode('utf-8'))
    spans = []
    if suffix == '.py':
        try:
            for token in tokenize.generate_tokens(io.StringIO(text).readline):
                if token.type == tokenize.COMMENT:
                    spans.append((at(*token.start), at(*token.end)))
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                    first = node.body[0]
                    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                        spans.append((offsets[first.lineno - 1] + first.col_offset,
                                      offsets[first.end_lineno - 1] + first.end_col_offset))
        except (SyntaxError, tokenize.TokenError, IndentationError):
            raise ValueError('Cannot inspect source comments: ' + name)
    elif suffix in ('.c', '.h', '.inc', '.cpp', '.hpp', '.cc'):
        expression = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
        for match in re.finditer(expression, text):
            if match.group().startswith(('//', '/*')):
                spans.append((byte_offset(match.start()), byte_offset(match.end())))
    elif suffix in ('.sh', '.cmake', '.ld', '.txt', '.ps1') or PurePosixPath(name).name == 'CMakeLists.txt':
        for match in re.finditer(r'(?m)^\s*#[^\n]*', text):
            spans.append((byte_offset(match.start()), byte_offset(match.end())))
    return sorted(set(spans))


def findings(files, *, absolute_paths=True):
    hits = []
    def add(name, rule, offset, encoding='ascii'):
        hits.append(dict(member=name, rule=rule, offset=offset, encoding=encoding))
    def inspect(name, data, depth=0, is_name=False):
        if depth > 8:
            raise ValueError('Nested ZIP scan depth exceeded')
        approved_profiles = [pattern for suffix, digest, pattern, reason in REVIEWED_VENDOR_EXAMPLES
                             if not is_name and vendor_member(name) and name.endswith(('!' + suffix, '/' + suffix))
                             and hashlib.sha256(data).hexdigest() == digest]
        for encoding, start in (('ascii', 0), ('utf-16le', 0), ('utf-16le', 1), ('utf-16be', 0), ('utf-16be', 1)):
            text = data.decode('latin-1') if encoding == 'ascii' else data[start:].decode(encoding, errors='ignore')
            width = 1 if encoding == 'ascii' else 2
            for match in re.finditer(re.escape(PRIVATE_NAME), text, re.I):
                handle = re.search(r'(?:github\.com/|x\.com/|twitter\.com/|@)$', text[:match.start()], re.I)
                if handle and (match.end() == len(text) or text[match.end()] in '/ \t\r\n"<>'):
                    continue
                add(name, 'private-name', start + match.start() * width, encoding)
            if not approved_notice(name) or is_name:
                for match in OWNER.finditer(text):
                    add(name, 'owner-name', start + match.start() * width, encoding)
            if absolute_paths:
                for rule, offset in private_path_findings(text, name, approved_profiles):
                    add(name, rule, start + offset * width, encoding)
        if is_name:
            return
        for begin, end in comment_spans(name, data):
            comment = data[begin:end].decode('utf-8')
            for match in INTERNAL.finditer(comment):
                add(name, 'internal-attribution', begin + len(comment[:match.start()].encode('utf-8')))
        if name.lower().endswith('.pyc'):
            if data[:4] != importlib.util.MAGIC_NUMBER:
                raise ValueError('Unsupported bytecode magic: ' + name)
            try:
                code = marshal.loads(data[16:])
            except (ValueError, EOFError, TypeError) as exc:
                raise ValueError('Invalid bytecode: ' + name) from exc
            def code_names(value):
                if not isinstance(value, types.CodeType):
                    raise ValueError('Bytecode has no code object: ' + name)
                for rule, offset in private_path_findings(value.co_filename, name):
                    add(name, 'bytecode-' + rule, offset, 'co_filename')
                for child in value.co_consts:
                    if isinstance(child, types.CodeType):
                        code_names(child)
            code_names(code)
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    if not info.is_dir():
                        child = name + '!' + info.filename
                        inspect(child + ' (name)', info.filename.encode(), depth + 1, True)
                        inspect(child, archive.read(info), depth + 1)
    for name, data in files.items():
        inspect(name + ' (name)', name.encode(), is_name=True)
        inspect(name, data)
    return hits


def read_kit(path):
    if path.is_dir():
        result = {}
        for member in sorted(path.rglob('*')):
            if member.is_symlink():
                raise ValueError('Kit contains a symlink')
            if member.is_file():
                result[member.relative_to(path).as_posix()] = member.read_bytes()
        return result
    with zipfile.ZipFile(path) as archive:
        result = {}
        for member in archive.infolist():
            name = member.filename
            if member.is_dir():
                continue
            parts = PurePosixPath(name).parts
            if name.startswith(('/', '\\')) or '..' in parts or '\\' in name or name in result:
                raise ValueError('Unsafe or duplicate ZIP member')
            result[name] = archive.read(member)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kit', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    files = read_kit(args.kit)
    hits = findings(files)
    report = dict(status='FAIL' if hits else 'PASS', files=len(files), hits=hits,
                  allowed_path_patterns=[dict(pattern=p, reason=r) for p, r in ALLOWED_PATH_PATTERNS],
                  allowed_context_patterns=[dict(pattern=p, reason=r) for p, r in ALLOWED_CONTEXT_PATTERNS],
                  reviewed_vendor_examples=[dict(member=n,sha256=s,pattern=p,reason=r)
                                            for n,s,p,r in REVIEWED_VENDOR_EXAMPLES])
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(status=report['status'], files=len(files), hits=len(hits))))
    return int(bool(hits))


if __name__ == '__main__':
    sys.exit(main())
