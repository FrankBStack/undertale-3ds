"""Route Stage 2 of X-F1-Full prototype through frozen emitted entry operands."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vine_old_parent as parent

INTERNAL = (
    'drawTowerStrips',
    'clearBoundTarget',
    'CtrRenderer_beginFrame',
)


# DELTARUNE New (flowergpu): tower face retention wraps the clear, the tower draw and flushLazy; cut 2 (rows
# nobody samples) also drawSurfaceImpl; cut 5b (vertex ring) reserveBatch, to tell frames apart at their first draw;
# cut 4b (plain layer copies in VRAM) yieldMirrors and reclaimVram, which give the copies up first.
INTERNAL_NEW = (
    'drawTowerStrips',
    'clearBoundTarget',
    'flushLazy',
    'drawSurfaceImpl',
    'reserveBatch',
    'yieldMirrors',
    'reclaimVram',
)


# Cut 3 (shared depth texture): drawTowerStrips' own two flushBatch calls only, so the second (the strips) can be
# drawn from the shared texture; every other flushBatch call is left as it is.
SCOPED_NEW = (
    ('drawTowerStrips', 'flushBatch', 'Vine_tower_flushBatch', 2),
    # Cut 5b (vertex ring wrap without the GPU wait when it can't matter): makeVertexRoom's waits and its other wrap.
    ('reserveBatch', 'CtrGpu_waitIdle', 'Vine_ring_waitIdle', 2),
    ('reserveBatch', 'endFrameEarly', 'Vine_ring_endFrameEarly', 1),
    # Cut 6 (flowerhw): drawTowerStrips' one segment test also leaves out a segment wholly outside the scissor's rows.
    ('drawTowerStrips', 'quadOutsideView.part.0', 'Vine_tower_outsideView', 1),
    # titancpu L1 (lazy surface hand-off splits, vine_titancpu.inc): bindTarget's hand-off split only, its first
    # splitFrame call; the second is the inlined flushPendingStoresSharing's and stays.
    ('bindTarget.part.0', 'splitFrame', 'Titan_leaveSplit', 2, (0,)),
    # vrgen (flowerhw): every renderer's destroy forgets it in the tower code first (vine_new_retain.inc's end), which
    # then goes on to pillarDestroy, so a next renderer at the same address is new to it.
    ('screensDestroy', 'pillarDestroy', 'Vine_rendererGone', 1, 'b'),
    # titancpu L-F (vine_titancpu_lf.inc): the fountain mesh's two callers, pillarSurfaceQuad's call and
    # pillarEmitPageRegion's tail branch, go to its copy with tile reuse and the clip skip. fountainMeshRegion's own
    # body (and its two recursive calls of itself) stays as it is.
    ('pillarSurfaceQuad.isra.0', 'fountainMeshRegion', 'Titan_lfMeshRegion', 1),
    ('pillarEmitPageRegion', 'fountainMeshRegion', 'Titan_lfMeshRegion', 1, 'b'),
)

# titancpu sharebuf (ctr_renderer_sharebuf.inc, compiled in the helper pass only when CTRPORT_SHAREBUF is on): the
# calls that store, load, touch, unpark and create surfaces go to its wrappers, each in the one function named and
# counted, so ctr_renderer.c's code is compiled as without it. Every other call of these stays as it is.
SCOPED_SHAREBUF = (
    ('clearBoundTarget', 'loadSpill', 'shareLoad', 1),
    ('reserveBatch', 'loadSpill', 'shareLoad', 1),
    ('ctrSurfaceCopy', 'loadSpill', 'shareLoad', 1),
    ('surfaceTexture', 'flushPendingStore', 'shareFlush', 1),
    ('releaseIdleScratches', 'flushPendingStore', 'shareFlush', 1),
    ('bindTarget.part.0', 'flushPendingStore', 'shareFlush', 1),
    ('bindTarget.part.0', 'touchSurface', 'shareTouchBind', 1),
    ('surfaceTexture', 'touchSurface', 'shareTouchSample', 1),
    ('touchSurface', 'unparkSurface', 'shareUnpark', 1, 'b'),
    ('ctrCreateSurface', 'createSurface', 'shareCreate', 1),
)

# sharebuf G2 (ctr_renderer_sharebuf_g2.inc, with CTRPORT_SHAREBUF_G2 too): bindTarget's touch and the three loads go
# to G2's wrappers instead of G1's (which they then call), the whole clear's memory fill to shareClear, and every
# delete of a scratch's target to shareTargetDelete. Against the G1 build only these calls change
# (check_sharebuf_layout.py --g2).
SHAREBUF_G2_ROUTES = {
    ('bindTarget.part.0', 'touchSurface'): 'shareBindG2',
    ('clearBoundTarget', 'loadSpill'): 'shareLoadG2',
    ('reserveBatch', 'loadSpill'): 'shareLoadG2',
    ('ctrSurfaceCopy', 'loadSpill'): 'shareLoadG2',
}
SCOPED_SHAREBUF_G2 = tuple((f, c, SHAREBUF_G2_ROUTES.get((f, c), w)) + tuple(rest) for f, c, w, *rest in SCOPED_SHAREBUF) + (
    ('clearBoundTarget', 'C3D_FrameBufClear', 'shareClear', 1),
    ('processDeferredFrees', 'C3D_RenderTargetDelete', 'shareTargetDelete', 2),
    ('releaseIdleScratches', 'C3D_RenderTargetDelete', 'shareTargetDelete', 1),
)

# titancpu L1: the whole clear and surfaceTexture go through titancpu's wrappers (the clear's then to Vine_wrap_);
# L2: drawSurfaceImpl too (its long way then to Vine_wrap_).
TARGETS_NEW = {'clearBoundTarget': 'Titan_wrap_clearBoundTarget', 'surfaceTexture': 'Titan_wrap_surfaceTexture',
               'drawSurfaceImpl': 'Titan_wrap_drawSurfaceImpl'}


# The VRAM probe (test only) also routes surfaceTexture, when vine_new_retain.inc turns it on.
PROBE_INC = Path(__file__).resolve().parents[2] / 'platform' / '3ds' / 'source' / 'vine_new_retain.inc'


def vram_probe_on():
    return any(line.startswith('#define CTRPORT_FLOWERGPU_VRAMPROBE') for line in PROBE_INC.read_text(encoding='utf-8').splitlines())


def retain_oomport_slots(assembly):
    # Both functions remain in their original contiguous late input section.
    # Checked growth and reset helpers shrink them; keep the original extents,
    # with an assembly error for growth. check_oomport_layout proves that each
    # zero tail follows a terminal barrier and has no incoming branch/address.
    for name, size in (('vineEnsureVramForFaces', 940), ('vineActivateStage2', 2624)):
        pattern = rf'(?m)^([ \t]*\.size[ \t]+{name},[ \t]*\.-{name}[ \t]*)$'
        fence = f'oomport_tail_{name}:\n\t.org {name}+{size}\n'
        assembly, count = re.subn(pattern, lambda m: fence + m[0], assembly)
        assert count == 1, ('missing/duplicate retained tower body', name, count)
    return assembly


# flowerhw tshare (DELTARUNE New): vrTowerDraw's one call of vdFrame goes to tsFrame (vine_new_retain.inc's end), which
# runs cut 3's step 0 itself and hands every other frame to vdFrame. Routed here, in the helper's late assembly, so the C
# call graph, and with it GCC's order of the flowergpu functions, stays as it was: a C call moved them all.
def route_tshare(extra):
    if not re.search(r'(?m)^tsFrame:$', extra):
        assert vram_probe_on(), 'tshare: no tsFrame'
        return extra
    found = list(re.finditer(r'(?ms)^vrTowerDraw:\r?\n.*?^\s*\.size\s+vrTowerDraw,\s*\.-vrTowerDraw\s*$', extra))
    assert len(found) == 1, 'tshare: vrTowerDraw'
    body, calls = re.subn(r'(?m)^([ \t]+bl[ \t]+)vdFrame([ \t]*(?:@[^\n]*)?)$', r'\1tsFrame\2', found[0][0])
    assert calls == 1, ('tshare: vdFrame calls in vrTowerDraw', calls)
    return extra[:found[0].start()] + body + extra[found[0].end():]


# titancpu L-F (DELTARUNE New): Titan_lfMeshRegion's own calls go where the renderer's do. Its inlined
# reserveVertices calls reserveBatch, which every renderer call reaches through Vine_wrap_reserveBatch (INTERNAL_NEW);
# route that one call the same way, and check that the copy calls no other routed entry.
def route_lf(extra):
    found = list(re.finditer(r'(?ms)^Titan_lfMeshRegion:\r?\n.*?^\s*\.size\s+Titan_lfMeshRegion,\s*\.-Titan_lfMeshRegion\s*$', extra))
    assert len(found) == 1, 'L-F: Titan_lfMeshRegion'
    body, counts = found[0][0], {}
    for name in parent.INTERNAL:
        target = parent.TARGETS.get(name, 'Vine_wrap_' + name)
        pattern = r'(?m)^([ \t]+b(?:l)?' + parent.extract.CONDITION + r'[ \t]+)' + re.escape(name) + r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$'
        body, counts[name] = re.subn(pattern, lambda m: m[1] + target + (m[2] or '') + m[3], body)
        assert not re.search(r'(?m)^[ \t]+\.word[ \t]+' + re.escape(name) + r'[ \t]*$', body), ('L-F: pointer', name)
    assert counts['reserveBatch'] == 1 and sum(counts.values()) == 1, ('L-F: routed calls', counts)
    return extra[:found[0].start()] + body + extra[found[0].end():]


def main():
    if '-DENABLE_WAD16' in sys.argv:
        import utwindow_compile
        return utwindow_compile.main(sys.argv[1:])
    internal = INTERNAL_NEW if '-DCTRPORT_TARGET_N3DS' in sys.argv else INTERNAL
    if internal is INTERNAL_NEW:
        # surfaceTexture: titancpu's sample stamps (and the VRAM probe after them, when it is on).
        internal = INTERNAL_NEW + ('surfaceTexture',)
    parent.TARGETS = TARGETS_NEW if internal is not INTERNAL else {}
    parent.INTERNAL = internal
    parent.EXTERNAL = ()
    parent.ENTRIES = internal
    sharebuf = internal is not INTERNAL and '-DCTRPORT_SHAREBUF' in sys.argv
    if sharebuf and '-DCTRPORT_SHAREBUF_G2' in sys.argv:
        sharebuf_routes = SCOPED_SHAREBUF_G2
    else:
        sharebuf_routes = SCOPED_SHAREBUF if sharebuf else ()
    parent.SCOPED = SCOPED_NEW + sharebuf_routes if internal is not INTERNAL else (
        ('drawSurfaceQuad', 'replayRecorded', 'Drpix_replay', 1, 'b'),
        ('drawSurfaceQuad', 'pillarSurfaceQuad.isra.0', 'Drpix_surfaceQuad', 1, 'b'),
    )
    return parent.main(retain_oomport_slots if internal is INTERNAL else (lambda extra: route_lf(route_tshare(extra))))


if __name__ == '__main__':
    sys.exit(main())
