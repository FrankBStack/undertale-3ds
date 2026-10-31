"""Keep named new AOT reference arrays inside the retained AOT text budget.

Only section attributes change; every initializer and binding stays intact.
Use with a padded single-table build and prove its layout after linking.
The generated file remains private game-derived build output.
"""
from pathlib import Path
import re

ATTRIBUTE = ' __attribute__((section(".text.aotf_padrefs"), aligned(4)))'


def names(path):
    selected = [line.split('#', 1)[0].strip() for line in Path(path).read_text(encoding='utf-8').splitlines()]
    selected = [name for name in selected if name]
    if not selected or len(set(selected)) != len(selected) or any(
            not re.fullmatch(r'gml_[A-Za-z0-9_]+', name) for name in selected):
        raise ValueError('Expected distinct AOT entry names in ' + str(path))
    return selected


def place(text, selected):
    """Return source with only the named entries' reference declarations decorated."""
    if ATTRIBUTE in text:
        raise ValueError('Reference arrays were already placed')
    entries = re.findall(r'^\s*\{ "([^"\n]+)",[^\n]*\baotv_(\d+), \d+, aotfn_\2, \d+ \},$', text, re.M)
    if len(dict(entries)) != len(entries):
        raise ValueError('Duplicate generated AOT entry names')
    indexes = dict(entries)
    original = text
    for name in selected:
        if name not in indexes:
            raise ValueError('Requested retained references are not selected: ' + name)
        for kind, prefix in (('AotVarRef', 'aotv_'), ('AotFuncRef', 'aotfn_')):
            declaration = 'static const %s %s%s[]' % (kind, prefix, indexes[name])
            if text.count(declaration + ' = {') != 1:
                raise ValueError('Missing or duplicate generated declaration: ' + declaration)
            text = text.replace(declaration + ' = {', declaration + ATTRIBUTE + ' = {', 1)
    assert text.replace(ATTRIBUTE, '') == original
    return text


def apply(directory, manifest):
    table = Path(directory) / 'aot_table.c'
    selected = names(manifest)
    placed = place(table.read_text(encoding='utf-8'), selected)
    with table.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(placed)
    print('AOT: retained reference arrays for %d entries; prove padded layout before timing' % len(selected))
