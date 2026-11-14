"""Guarded boost cleanup routing inside the existing audpar launcher.

Only the two final frees of CtrAudioSystem change target. All member frees,
instruction slots and the original launcher nesting stay unchanged.
"""
import re


def retarget_system_free(text):
    matches = list(re.finditer(r'^ctrDestroy:\n.*?^\s*\.size\s+ctrDestroy,[^\n]*\n', text, re.M | re.S))
    assert len(matches) == 1, 'missing/duplicate ctrDestroy'
    body = matches[0][0]
    instructions = []
    for line in body.splitlines():
        code = line.split('@', 1)[0].strip()
        if code and not code.startswith('.') and not code.endswith(':'):
            instructions.append(code)
    assert instructions.count('mov\tr6, r0') == 1, 'system register changed'
    assert not any(re.match(r'(?:mov|ldr|add|sub|ldm)\w*\s+r6\b', code)
                   and code != 'mov\tr6, r0' for code in instructions), 'system register overwritten'
    exits = [i for i, code in enumerate(instructions) if re.fullmatch(r'b\s+free', code)]
    assert len(exits) == 2, 'expected two system-free tail exits'
    for index in exits:
        assert instructions[index - 2:index] == ['mov\tr0, r6', 'pop\t{r4, r5, r6, lr}'], 'not a system-free exit'
    patched, count = re.subn(r'(^[ \t]*b[ \t]+)free([ \t]*$)',
                             r'\1CtrAudioBoost_free\2', body, flags=re.M)
    assert count == 2
    return text[:matches[0].start()] + patched + text[matches[0].end():]
