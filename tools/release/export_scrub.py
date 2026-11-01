"""Deterministic, token-checked cleanup of distribution copies only.

No caller writes the input tree. Byte offsets and line terminators are retained,
so C preprocessor line numbers and diagnostics keep their original positions.
"""
import ast
import hashlib
from pathlib import PurePosixPath
import re

import check_kit_hygiene as hygiene


def editable_spans(name, data):
    """Comments/docstrings and literal argparse help, never executable strings."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == '.rsf':
        return hygiene.comment_spans(name + '.txt', data)
    if suffix in ('.md',):
        # These documentation files are not compiler inputs. Fenced examples
        # remain protected, including examples that happen to look like prose.
        spans = []
        offset = 0
        fence = None
        for line in data.splitlines(keepends=True):
            marker = re.match(rb'\s*(```+|~~~+)', line)
            if marker:
                token = marker.group(1)[:1]
                fence = None if fence == token else token
            elif fence is None:
                spans.append((offset, offset + len(line)))
            offset += len(line)
        return spans
    if suffix == '.py':
        spans = hygiene.comment_spans(name, data)
        lines = data.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        tree = ast.parse(data)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = node.func.attr if isinstance(node.func, ast.Attribute) else ''
            if method not in ('add_argument', 'ArgumentParser'):
                continue
            for keyword in node.keywords:
                value = keyword.value
                if keyword.arg in ('help', 'description', 'epilog') and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    spans.append((offsets[value.lineno - 1] + value.col_offset,
                                  offsets[value.end_lineno - 1] + value.end_col_offset))
        return sorted(set(spans))
    if suffix in ('.cmake', '.ld', '.sh', '.txt', '.ps1') or PurePosixPath(name).name == 'CMakeLists.txt':
        # A small lexical scanner protects quoted/bracket strings and shell
        # heredocs. Only actual hash comments can authorize an edit.
        text = data.decode('utf-8')
        spans = []
        i = 0
        heredoc = None
        while i < len(text):
            if heredoc is not None:
                end = text.find('\n', i)
                end = len(text) if end < 0 else end + 1
                if text[i:end].strip() == heredoc:
                    heredoc = None
                i = end
                continue
            if text.startswith('<<', i) and suffix == '.sh':
                match = re.match(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z_0-9]*)['\"]?[^\n]*\n", text[i:])
                if match:
                    heredoc = match.group(1)
                    i += match.end()
                    continue
            bracket = re.match(r'\[(=*)\[', text[i:]) if text[i] == '[' else None
            if bracket:
                end = text.find(']' + bracket.group(1) + ']', i + bracket.end())
                if end < 0:
                    raise ValueError('Unclosed bracket string: ' + name)
                i = end + len(bracket.group(1)) + 2
                continue
            if text[i] in ('"', "'", '`'):
                quote = text[i]
                i += 1
                while i < len(text):
                    if text[i] == '\\':
                        i += 2
                    elif text[i] == quote:
                        i += 1
                        break
                    else:
                        i += 1
                continue
            if text[i] == '#' and (i == 0 or text[i - 1].isspace()):
                end = text.find('\n', i)
                end = len(text) if end < 0 else end
                spans.append((len(text[:i].encode('utf-8')), len(text[:end].encode('utf-8'))))
                i = end
            else:
                i += 1
        return spans
    return hygiene.comment_spans(name, data)


def checked_rewrite(name, data, edits):
    """Apply explicit edits only inside recognized text; refuse code-token edits."""
    spans = editable_spans(name, data)
    previous = 0
    result = bytearray(data)
    for start, end, replacement in sorted(edits):
        if (start < previous or not 0 <= start < end <= len(data)
                or not any(a <= start and end <= b for a, b in spans)):
            raise ValueError('Export scrub would touch a code token: ' + name)
        original = data[start:end]
        if len(original) != len(replacement) or [i for i, c in enumerate(original) if c in (10, 13)] != [i for i, c in enumerate(replacement) if c in (10, 13)]:
            raise ValueError('Export scrub would change line positions: ' + name)
        # Comment/string delimiters and escape characters cannot be altered,
        # even though they fall within a recognized editable span.
        for i, (before, after) in enumerate(zip(original, replacement)):
            if before != after and before in b'\n\r\\\'"#/*`':
                raise ValueError('Export scrub would change a delimiter: ' + name)
        result[start:end] = replacement
        previous = end
    result = bytes(result)
    if editable_spans(name, result) != spans:
        raise ValueError('Export scrub changed token boundaries: ' + name)
    return result


def scrub_member(name, data):
    """Remove attribution from editable text; remaining leaks fail the kit gate."""
    # The top-level README is the public project page (written for release, mapped from
    # tools/release/templates/): its author's name and the AI-use note are meant to be there.
    if name == 'README.md' or hygiene.approved_notice(name) or b'\0' in data:
        return data
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return data
    if not hygiene.INTERNAL.search(text) and not hygiene.OWNER.search(text):
        return data
    edits = []
    for start, end in editable_spans(name, data):
        text = data[start:end].decode('utf-8')
        matches = list(hygiene.INTERNAL.finditer(text)) + list(hygiene.OWNER.finditer(text))
        # Private paths/names in source comments are rejected by the final gate;
        # never rewrite a path or a literal that might affect build behavior.
        occupied = set()
        for match in matches:
            a = start + len(text[:match.start()].encode('utf-8'))
            b = start + len(text[:match.end()].encode('utf-8'))
            if any(i in occupied for i in range(a, b)):
                continue
            original = data[a:b]
            replacement = bytes(c if c in (10, 13) else 32 for c in original)
            edits.append((a, b, replacement))
            occupied.update(range(a, b))
    return checked_rewrite(name, data, edits) if edits else data


def scrub_files(files):
    """Return new bytes; an idempotent shared public-export/kit transformation."""
    result = {name: scrub_member(name, data) for name, data in sorted(files.items())}
    # Identifier approvals stay bound to their exact original preimage. Only
    # entries matching that preimage can acquire the scrubbed copy's digest.
    import json
    policy_name = 'tools/release/identifier-allowlist.json'
    if policy_name in result:
        policy = json.loads(result[policy_name])
        changed = False
        for entry in policy['entries']:
            name = entry['member']
            if name in files and result[name] != files[name] and hashlib.sha256(files[name]).hexdigest() == entry['sha256']:
                entry['sha256'] = hashlib.sha256(result[name]).hexdigest()
                changed = True
        if changed:
            # Metadata only: keep every original line and replace the exact
            # digest token rather than reformatting the policy document.
            raw = result[policy_name]
            old_policy = json.loads(raw)
            for old, new in zip(old_policy['entries'], policy['entries']):
                if old['sha256'] != new['sha256']:
                    # Replace within this entry's member-delimited object.
                    needle = re.compile(rb'("member"\s*:\s*' + re.escape(json.dumps(old['member']).encode()) + rb'[\s\S]*?"sha256"\s*:\s*")' + old['sha256'].encode())
                    raw, count = needle.subn(lambda m: m.group(1) + new['sha256'].encode(), raw)
                    if count != 1:
                        raise ValueError('Ambiguous export approval metadata')
            result[policy_name] = raw
    return result
