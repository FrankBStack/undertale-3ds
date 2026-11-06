"""Shared devkitARM discovery for optional host-side compiler/assembler tests."""
import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'release/builder'))
import toolchain

REQUIRE = 'REQUIRE_DEVKITARM'


def arm_tools(*names):
    """DEVKITARM, DEVKITPRO, builder install roots, then a sibling tool set on PATH.

    Match test_loadgame_compile's policy: skip if absent unless REQUIRE_DEVKITARM is set.
    """
    names = names or ('as', 'objcopy')
    suffix = '.exe' if os.name == 'nt' else ''
    roots = [Path(os.environ['DEVKITARM']) / 'bin'] if os.environ.get('DEVKITARM') else []
    if os.environ.get('DEVKITPRO'):
        roots.append(Path(os.environ['DEVKITPRO']) / 'devkitARM/bin')
    roots.extend(Path(root) / 'devkitARM/bin' for root in toolchain.candidate_roots())
    for folder in roots:
        tools = [folder / ('arm-none-eabi-' + name + suffix) for name in names]
        if all(tool.is_file() for tool in tools):
            return list(map(str, tools))
    first = shutil.which('arm-none-eabi-' + names[0])
    if first:
        tools = [Path(first).with_name('arm-none-eabi-' + name + suffix) for name in names]
        if all(tool.is_file() for tool in tools):
            return list(map(str, tools))
    message = ('devkitARM ' + ', '.join(names) + ' are not available through DEVKITARM, DEVKITPRO, '
               'the standard devkitPro install locations or PATH')
    if os.environ.get(REQUIRE):
        raise AssertionError(message)
    raise unittest.SkipTest(message)
