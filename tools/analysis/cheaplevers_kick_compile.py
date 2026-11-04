"""Retain ordinary assembly and append only kick late sections.

The ordinary renderer still goes through the existing vine launcher. Nothing
from the kick helper pass's ordinary bodies, data or strings is retained.
Object-byte/relocation preflight and full linked layout remain independent gates.
The forced-pressure allocator diagnostic additionally routes exactly two calls
in its retained ordinary body; it never selects that path for production.

KM rev 5 (change pacer, the 75zq append-only port, c26rev R131 F2): the queue and
renderer objects get a second helper pass with CTR_KICK_REV5 (ctr_gpu_kick5.inc,
ctr_gpu_kick5_renderer.inc). The first pass is KM rev 4.1's, unchanged: its late
sections keep every address, size and name. Every symbol the second pass defines
is renamed Km5_<name> (its two new wrappers excepted), and each exported rev 4.1
function's first instruction becomes a branch to its Km5_ twin (same size), so
every existing caller, linker wrap and routed call reaches rev 5.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vine_extract as extract

SEPARATOR = '--kick-cc--'
LANE = 'cheaplevers_kick'


def rename_export(text, old, new):
    """Rename a helper definition, rejecting references outside its metadata."""
    assert not re.search(r'(?m)^'+new+r':$', text), ('duplicate kick export', new)
    assert len(re.findall(r'(?m)^'+old+r':$', text)) == 1, ('missing kick export', old)
    lines = [line for line in text.splitlines() if re.search(r'\b'+old+r'\b', line)]
    allowed = (r'\s*\.global\s+'+old+r'\s*|\s*\.type\s+'+old+r',\s*%function\s*|'+
               old+r':|\s*\.size\s+'+old+r',\s*\.-'+old+r'\s*')
    assert lines and all(re.fullmatch(allowed, line) for line in lines), (old, lines)
    changed, count = re.subn(r'\b'+old+r'\b', new, text)
    return changed, dict(old=old, new=new, symbol_operands=count)


def benchmark_wait_route(text):
    """Keep benchfix's timing outside both the prefix join and physical fence."""
    proof = []
    for scope in ('__wrap_CtrGpu_waitDraws', 'bfDrawWaitTimed'):
        pattern = r'(?ms)^'+scope+r':\r?\n.*?^\s*\.size\s+'+scope+r',\s*\.-'+scope+r'\s*$'
        matches = list(re.finditer(pattern, text))
        assert len(matches) == 1, ('bench wait scope', scope, len(matches))
        body = matches[0][0]
        operand = (r'(?m)^([ \t]+b(?:l)?'+extract.CONDITION+r'[ \t]+)__real_CtrGpu_waitDraws'
                   r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$')
        changed, count = re.subn(operand, lambda m:m[1]+'CtrKick_chainWaitDraws'+(m[2] or '')+m[3], body)
        assert count == 1, ('bench wait target', scope, count)
        assert len(body.splitlines()) == len(changed.splitlines())
        text = text[:matches[0].start()]+changed+text[matches[0].end():]
        proof.append(dict(scope=scope, old='__real_CtrGpu_waitDraws',
                          new='CtrKick_chainWaitDraws', targets=count,
                          before_sha256=extract.sha(body), after_sha256=extract.sha(changed)))
    return text, proof


def lender_name(lender):
    """True: Knight GPU L-A's begin; a name: the wrapper the history chain calls instead (75zm: A's compaction)."""
    return lender if isinstance(lender, str) else 'KnightGpu_beginFrame'


def lender_flags(command):
    """The lender the build's Knight chain calls: none, L-A, or L-A through A's compaction (75zm)."""
    if '-DCTRPORT_KNIGHTGPU_LENDER' not in command:
        return False
    return 'KnightGpu_compactBeginFrame' if '-DCTRPORT_KNIGHTGPU_COMPACT_ON' in command else True


def history_route(text, lender=False):
    """Keep the Knight wrappers, including its lender; redirect two calls."""
    proof = []
    for frame in ('begin', 'end'):
        scope = '__wrap_CtrRenderer_'+frame+'Frame'
        pattern = r'(?ms)^'+scope+r':\r?\n.*?^\s*\.size\s+'+scope+r',\s*\.-'+scope+r'\s*$'
        matches = list(re.finditer(pattern, text))
        assert len(matches) == 1, ('Knight chain scope', scope, len(matches))
        body = matches[0][0]
        old = lender_name(lender) if lender and frame == 'begin' else '__real_CtrRenderer_'+frame+'Frame'
        new = 'CtrKick_chain'+frame.title()+'Frame'
        operand = r'(?m)^([ \t]+b(?:l)?'+extract.CONDITION+r'[ \t]+)'+old+r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$'
        changed, count = re.subn(operand, lambda m: m[1]+new+(m[2] or '')+m[3], body)
        assert count == 1, ('Knight chain call', scope, count)
        assert len(body.splitlines()) == len(changed.splitlines())
        text = text[:matches[0].start()]+changed+text[matches[0].end():]
        proof.append(dict(scope=scope, old=old, new=new, targets=count,
                          before_sha256=extract.sha(body), after_sha256=extract.sha(changed)))
    return text, proof


def renderer_history_route(text, lender=False):
    """Adapt retained kick helpers to the current history/lender wrapper chain.

    The C helper still uses the legacy history macro. Rename only its exported
    frame entry points, then send Begin through the existing lender when enabled.
    No ordinary renderer or lender assembly comes from this helper pass.
    """
    proof = []
    for frame in ('begin', 'end'):
        old = '__wrap_CtrRenderer_'+frame+'Frame'
        new = 'CtrKick_chain'+frame.title()+'Frame'
        assert not re.search(r'(?m)^'+new+r':$', text), ('duplicate kick chain', new)
        assert len(re.findall(r'(?m)^'+old+r':$', text)) == 1, ('missing kick export', old)
        lines = [line for line in text.splitlines() if re.search(r'\b'+old+r'\b', line)]
        allowed = (r'\s*\.global\s+'+old+r'\s*|\s*\.type\s+'+old+r',\s*%function\s*|'+
                   old+r':|\s*\.size\s+'+old+r',\s*\.-'+old+r'\s*')
        assert lines and all(re.fullmatch(allowed, line) for line in lines), (old, lines)
        text, count = re.subn(r'\b'+old+r'\b', new, text)
        proof.append(dict(old=old, new=new, symbol_operands=count))
    if lender:
        scope = 'CtrKick_chainBeginFrame'
        pattern = r'(?ms)^'+scope+r':\r?\n.*?^\s*\.size\s+'+scope+r',\s*\.-'+scope+r'\s*$'
        matches = list(re.finditer(pattern, text))
        assert len(matches) == 1
        body = matches[0][0]
        operand = (r'(?m)^([ \t]+b(?:l)?'+extract.CONDITION+r'[ \t]+)__real_CtrRenderer_beginFrame'
                   r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$')
        changed, count = re.subn(operand, lambda m:m[1]+lender_name(lender)+(m[2] or '')+m[3], body)
        assert count == 1, ('kick helper lender target', count)
        text = text[:matches[0].start()]+changed+text[matches[0].end():]
        proof.append(dict(scope=scope, old='__real_CtrRenderer_beginFrame',
                          new=lender_name(lender), targets=count))
    return text, proof


def pressure_route(text):
    """Debug only: two operands in the unchanged original allocator body."""
    scope = 'CtrMemory_linearAllocOnce'
    pattern = r'(?ms)^' + scope + r':\r?\n.*?^\s*\.size\s+' + scope + r',\s*\.-' + scope + r'\s*$'
    matches = list(re.finditer(pattern, text))
    assert len(matches) == 1, ('pressure scope', len(matches))
    body = matches[0][0]
    operand = (r'(?m)^([ \t]+b(?:l)?' + extract.CONDITION + r'[ \t]+)__real_linearAlloc'
               r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$')
    changed, count = re.subn(operand, lambda m: m[1] + 'CtrKick_testLinearAlloc' +
                             (m[2] or '') + m[3], body)
    assert count == 2, ('pressure targets', count)
    assert len(body.splitlines()) == len(changed.splitlines())
    proof = dict(scope=scope, targets=count, old='__real_linearAlloc', new='CtrKick_testLinearAlloc',
                 before_sha256=extract.sha(body), after_sha256=extract.sha(changed))
    return text[:matches[0].start()] + changed + text[matches[0].end():], proof


def end_flush_route(text):
    """One same-size call in each closing path, before suffix submission."""
    proof=[]
    for scope in ('C3D_FrameEnd','CtrGpu_frameEndBehind'):
        pattern = r'(?ms)^'+scope+r':\r?\n.*?^\s*\.size\s+'+scope+r',\s*\.-'+scope+r'\s*$'
        matches = list(re.finditer(pattern, text))
        assert len(matches) == 1, ('frame end scope', scope, len(matches))
        body = matches[0][0]
        operand = (r'(?m)^([ \t]+bl'+extract.CONDITION+r'[ \t]+)GSPGPU_FlushDataCache'
                   r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$')
        changed, count = re.subn(operand, lambda m:m[1]+'CtrKick_endFlush'+(m[2] or '')+m[3], body)
        assert count == 1, ('frame end flush targets', scope, count)
        assert len(body.splitlines()) == len(changed.splitlines())
        text=text[:matches[0].start()]+changed+text[matches[0].end():]
        proof.append(dict(scope=scope, old='GSPGPU_FlushDataCache', new='CtrKick_endFlush',
            targets=count, before_sha256=extract.sha(body), after_sha256=extract.sha(changed)))
    return text,proof


# KM rev 5: the second pass's late sections, its symbol prefix and the two wrappers it adds (linked by name).
REV5 = 'pacer_km5'
REV5_PREFIX = 'Km5_'
REV5_KEEP = ('__wrap_gxCmdQueueRun', '__wrap_CtrPacer_stressStep')
# Only rev 5's pass reads it (CMake gives it to ctr_gpu_queue.c in gpukick-trace builds).
REV5_ONLY = ('-DCTR_KICK_FRAME_TRACE',)
# Log formats rev 5 declares extern and prints from rev 4.1's retained objects (c26rev R147 F2).
REV5_SHARED = ('kickLog', 'kickTraceLog')
SYMBOL = r'[A-Za-z_$][\w.$]*'


def rev5_prefix(text, keep=REV5_KEEP):
    """Rename every symbol the rev 5 pass defines, and its calls of rev 5's exports in the other object (CtrKick_*),
    to Km5_<name>: no rev 4.1 name, and no name of the base's other objects, is defined twice."""
    defined = set(re.findall(r'(?m)^('+SYMBOL+r'):', text)) - {n for n in re.findall(r'(?m)^(\.L[\w.$]*):', text)}
    defined = {n for n in defined if not n.startswith('.')}
    for name in keep:
        assert name not in defined or re.search(r'(?m)^\s*\.global\s+'+re.escape(name)+r'\s*$', text), name
    names = (defined | set(re.findall(r'(?<![\w.$])(CtrKick_\w+)(?![\w$.])', text))) - set(keep)
    assert not any(n.startswith(REV5_PREFIX) for n in names), 'rev 5 already prefixed'
    counts = dict.fromkeys(names, 0)
    lines = text.split('\n')
    for at, line in enumerate(lines):
        if re.match(r'\s*\.(?:ascii|asciz|string)\b', line):
            continue  # log formats ("GPU kick: ...") keep their text
        for name in sorted(names, key=len, reverse=True):
            line, n = re.subn(r'(?<![\w.$])'+re.escape(name)+r'(?![\w$.])', REV5_PREFIX+name, line)
            counts[name] += n
        lines[at] = line
    assert all(counts.values()), 'a rev 5 name was never renamed'
    return '\n'.join(lines), dict(defined=sorted(defined), renamed=counts, kept=[n for n in keep if n in defined])


def rev5_shared(rev41, rev5, names=REV5_SHARED):
    """Rev 5 refers to each shared format and never defines it; rev 4.1 defines it (a local label of the same
    assembly file, so the assembler resolves rev 5's references there; rev5_prefix renames only definitions)."""
    for name in names:
        assert re.search(r'(?m)^'+re.escape(name)+r':$', rev41), ('rev 4.1 lacks', name)
        assert not re.search(r'(?m)^'+re.escape(name)+r':$', rev5), ('rev 5 defines', name)
        assert re.search(r'(?<![\w.$])'+re.escape(name)+r'(?![\w$.])', rev5), ('rev 5 never uses', name)
    return list(names)


def rev41_trampolines(text, twins):
    """Each exported rev 4.1 function's first instruction becomes `b Km5_<name>`: same size and address, every
    existing caller reaches rev 5. Its remaining (now unreached) instructions, constants and state stay in place."""
    assert not re.search(r'(?m)^\s*\.thumb', text), 'rev 4.1 kick code is ARM'
    # The extracted assembly declares each global twice (the helper's .global and the extract's): once each here.
    exported = list(dict.fromkeys(n for n in re.findall(r'(?m)^\s*\.global\s+('+SYMBOL+r')\s*$', text)
                                  if re.search(r'(?m)^\s*\.type\s+'+re.escape(n)+r',\s*%function\s*$', text)))
    assert exported, 'no rev 4.1 export'
    lines = text.split('\n')
    proof = []
    for name in exported:
        assert name in twins, ('rev 4.1 export without a rev 5 twin', name)
        at = lines.index(name+':')
        i = at+1
        while not re.match(r'\t[a-z]', lines[i]) or lines[i].lstrip().startswith(('@', '.')):
            assert not re.match(r'(?m)^'+SYMBOL+r':$', lines[i]) or lines[i].startswith('.L'), (name, lines[i])
            i += 1
        old = lines[i]
        assert re.match(r'\t[a-z][a-z0-9.]*(\t|$)', old) and not old.lstrip().startswith(('.', '@')), (name, old)
        lines[i] = '\tb\t'+REV5_PREFIX+name
        proof.append(dict(name=name, replaced=old.strip(), branch=REV5_PREFIX+name))
    return '\n'.join(lines), proof


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=240).returncode


def no_dependencies(command):
    result = []
    at = 0
    while at < len(command):
        if command[at] in ('-MF', '-MT', '-MQ'):
            at += 2
            continue
        if command[at] not in ('-MD', '-MMD', '-MP'):
            result.append(command[at])
        at += 1
    return result


def main():
    args = sys.argv[1:]
    at = args.index(SEPARATOR)
    delegate, command = [x for x in args[:at] if x], args[at+1:]
    sources = [x for x in command if x.replace('\\', '/').endswith(
        ('/ctr_gpu_queue.c', '/ctr_renderer.c', '/ctr_memory.c', '/z_knightnew_history.c', '/ctr_benchmark.c'))]
    if not sources or '-DCTR_GPU_KICK' not in command:
        return run(delegate + command)
    memory = sources[0].replace('\\', '/').endswith('/ctr_memory.c')
    if memory and '-DCTR_KICK_FORCE_PRESSURE' not in command:
        return run(delegate + command)
    assert '-DENABLE_WAD17' in command and '-DCTRPORT_TARGET_N3DS' in command
    assert len(sources) == 1 and command.count('-o') == 1 and '-c' in command
    output = Path(command[command.index('-o')+1])
    files = {key: output.with_suffix('.kick-'+key+'.s')
             for key in ('original', 'helper', 'helper5', 'linked')}
    draw_wait = any(re.fullmatch(r'-DCTRPORT_BENCHFIX_DRAWWAIT(?:=1)?', x) for x in command)
    if sources[0].replace('\\', '/').endswith('/ctr_benchmark.c'):
        if not draw_wait:
            return run(delegate+command)
        # This source joins kick_sources only for the DR New kick trial, so
        # CMake tracks this launcher's dependency and both flag transitions.
        original = [x for x in command if x != '-DCTR_GPU_KICK']
        original[original.index('-c')] = '-S'
        original[original.index('-o')+1] = str(files['original'])
        rc = run(delegate+original)
        if rc:
            return rc
        baseline = files['original'].read_text(encoding='utf-8')
        linked, proof = benchmark_wait_route(baseline)
        files['linked'].write_bytes(linked.encode('utf-8'))
        assemble = no_dependencies(command)
        assemble = [x for x in assemble if x not in sources and x != '-c']
        assemble += ['-x', 'assembler', '-c', str(files['linked'])]
        rc = run(assemble)
        output.with_suffix('.kick-routing.json').write_text(json.dumps(dict(
            benchmark_wait_proof=proof, exit=rc,
            files={k:str(v) for k,v in files.items() if k != 'helper'},
            original_command=original, assembly_command=assemble), indent=2)+'\n', encoding='utf-8')
        return rc
    if sources[0].replace('\\', '/').endswith('/z_knightnew_history.c'):
        assert '-DCTRPORT_KNIGHTNEW_HISTORY' in command
        original = [x for x in command if x != '-DCTR_GPU_KICK']
        original[original.index('-c')] = '-S'
        original[original.index('-o')+1] = str(files['original'])
        rc = run(delegate+original)
        if rc:
            return rc
        baseline = files['original'].read_text(encoding='utf-8')
        linked, proof = history_route(baseline, lender=lender_flags(command))
        files['linked'].write_bytes(linked.encode('utf-8'))
        assemble = no_dependencies(command)
        assemble = [x for x in assemble if x not in sources and x != '-c']
        assemble += ['-x', 'assembler', '-c', str(files['linked'])]
        rc = run(assemble)
        output.with_suffix('.kick-routing.json').write_text(json.dumps(dict(
            history_proof=proof, exit=rc, files={k:str(v) for k,v in files.items() if k != 'helper'},
            original_command=original, assembly_command=assemble), indent=2)+'\n', encoding='utf-8')
        return rc
    # Memory keeps the production retirement hooks in its ordinary pass;
    # diagnostic-only helpers come from the independent pass, as for queues.
    original = [x for x in command if x != ('-DCTR_KICK_FORCE_PRESSURE' if memory else '-DCTR_GPU_KICK')
                and x not in REV5_ONLY]
    renderer = sources[0].replace('\\', '/').endswith('/ctr_renderer.c')
    if renderer:
        # Accepted tower retention is already supplied by this launcher.
        # Its linked assembly is exactly the object before adding kick code.
        rc = run(delegate + original)
        if rc:
            return rc
        baseline = output.with_suffix('.vine-linked.s').read_text(encoding='utf-8')
        files['original'].write_bytes(baseline.encode('utf-8'))
    else:
        original[original.index('-c')] = '-S'
        original[original.index('-o')+1] = str(files['original'])
        rc = run(original)
        if rc:
            return rc
        baseline = files['original'].read_text(encoding='utf-8')

    pressure_proof = None
    end_flush_proof = None
    if memory:
        baseline, pressure_proof = pressure_route(baseline)
    elif not renderer:
        baseline, end_flush_proof = end_flush_route(baseline)
    helper = no_dependencies(command)
    # The paired FCRAM diagnostic helper already belongs to the frozen
    # ordinary assembly. Do not append a second definition from this pass.
    helper = [x for x in helper if x != '-DCTR_KICK_SHARED_FCRAM' and x not in REV5_ONLY]
    helper[helper.index('-c')] = '-S'
    helper[helper.index('-o')+1] = str(files['helper'])
    helper += ['-fno-section-anchors']
    rc = run(helper)
    if rc:
        return rc
    extract.LATE_LANES[LANE] = re.compile(r'^\.(?:text|rodata|data|bss)\.late\.cheaplevers_kick$')
    helper_text = files['helper'].read_text(encoding='utf-8')
    for kind in ('text', 'rodata', 'data', 'bss'):
        helper_text = helper_text.replace('.'+kind+'.cheaplevers_kick_late', '.'+kind+'.late.'+LANE)
    extra, sections = extract.late_sections(helper_text, LANE)
    for kind in ('text', 'rodata', 'data', 'bss'):
        extra = extra.replace('.'+kind+'.late.'+LANE, '.'+kind+'.cheaplevers_kick_late')
    # The renderer's pre-existing vine helper already uses Flowery local labels.
    extra = extra.replace('.LFlowery_', '.LKick_').replace('FloweryLocal_', 'KickLocal_')
    renderer_history_proof = None
    benchmark_wait_export = None
    if not (renderer or memory) and draw_wait:
        extra, benchmark_wait_export = rename_export(
            extra, '__wrap_CtrGpu_waitDraws', 'CtrKick_chainWaitDraws')
    if renderer and '-DCTRPORT_KNIGHTNEW_HISTORY' in command:
        extra, renderer_history_proof = renderer_history_route(extra, lender=lender_flags(command))
    rev41_sha256 = hashlib.sha256(extra.encode()).hexdigest()
    rev5 = None
    extra5 = ''
    if not memory:
        # KM rev 5: the same helper pass with CTR_KICK_REV5 (and the trace define, if any); only its own late sections.
        helper5 = [x for x in no_dependencies(command) if x != '-DCTR_KICK_SHARED_FCRAM'] + ['-DCTR_KICK_REV5']
        helper5[helper5.index('-c')] = '-S'
        helper5[helper5.index('-o')+1] = str(files['helper5'])
        helper5 += ['-fno-section-anchors']
        rc = run(helper5)
        if rc:
            return rc
        extract.LATE_LANES[REV5] = re.compile(r'^\.(?:text|rodata|data|bss)\.late\.'+REV5+'$')
        helper5_text = files['helper5'].read_text(encoding='utf-8')
        assert '.cheaplevers_kick_late' not in helper5_text, 'rev 5 pass emitted rev 4.1 sections'
        for kind in ('text', 'rodata', 'data', 'bss'):
            helper5_text = helper5_text.replace('.'+kind+'.'+REV5+'_late', '.'+kind+'.late.'+REV5)
        extra5, sections5 = extract.late_sections(helper5_text, REV5)
        for kind in ('text', 'rodata', 'data', 'bss'):
            extra5 = extra5.replace('.'+kind+'.late.'+REV5, '.'+kind+'.'+REV5+'_late')
        extra5 = extra5.replace('.LFlowery_', '.LKm5_').replace('FloweryLocal_', 'Km5Local_')
        rev5 = dict(sections=sections5, helper_command=helper5)
        if not renderer and draw_wait:
            extra5, rev5['benchmark_wait_export'] = rename_export(
                extra5, '__wrap_CtrGpu_waitDraws', 'CtrKick_chainWaitDraws')
        if renderer and '-DCTRPORT_KNIGHTNEW_HISTORY' in command:
            extra5, rev5['renderer_history_proof'] = renderer_history_route(extra5, lender=lender_flags(command))
        if not renderer and '-DCTR_KICK_BENCH_TOTALS' in helper5:
            rev5['shared'] = rev5_shared(extra, extra5)
        extra5, rev5['prefix'] = rev5_prefix(extra5, REV5_KEEP if not renderer else ())
        if not renderer:
            assert all(n in rev5['prefix']['kept'] for n in REV5_KEEP), 'rev 5 wrappers missing'
        twins = {n[len(REV5_PREFIX):] for n in re.findall(r'(?m)^\s*\.global\s+('+SYMBOL+r')\s*$', extra5)
                 if n.startswith(REV5_PREFIX)}
        extra, rev5['trampolines'] = rev41_trampolines(extra, twins)
        rev5['helper_sha256'] = hashlib.sha256(extra5.encode()).hexdigest()
    files['linked'].write_bytes((baseline+'\n'+extra+('\n'+extra5 if extra5 else '')).encode('utf-8'))

    assemble = no_dependencies(command)
    assemble = [x for x in assemble if x not in sources and x != '-c']
    assemble += ['-x', 'assembler', '-c', str(files['linked'])]
    rc = run(assemble)
    receipt = dict(sections=sections, renderer=renderer, memory=memory, pressure_proof=pressure_proof,
                   renderer_history_proof=renderer_history_proof,
                   benchmark_wait_export=benchmark_wait_export,
                   end_flush_proof=end_flush_proof, exit=rc,
                   baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),
                   helper_sha256=hashlib.sha256(extra.encode()).hexdigest(),
                   rev41_extract_sha256=rev41_sha256, rev5=rev5,
                   files={k: str(v) for k, v in files.items()},
                   original_command=original, helper_command=helper,
                   assembly_command=assemble)
    output.with_suffix('.kick-routing.json').write_text(
        json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print('Kick: frozen ordinary assembly plus late sections '+json.dumps(sections)+
          ('' if rev5 is None else ' + KM rev 5 '+json.dumps(rev5['sections'])+', '+str(len(rev5['trampolines']))+
           ' rev 4.1 exports branch to it'), flush=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
