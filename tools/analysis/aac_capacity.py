"""UNDERTALE AAC slot capacities, one copy for the tools (N10 rider R9, review decision 11-15).

platform/3ds/aacout.cmake is the build's copy; test_aac_capacity.py proves the two agree, so a capacity change edits
aacout.cmake and this file and nothing else that gates current builds.

TEXT is each model's AAC text slot today:
  Old 80,260 B since the Old 1.0 envelope (relready-resize.md, integrate21 dv8q, 11-09);
  New 59,780 B since N10 rider R9 (+16 KiB from New's late reserve; review decision 11-15).
TEXT_RETIRED holds the text capacities that frozen builds still carry: 43,396 B was New's slot until N10 (and every
model's before dv8q). A layout pair must still have the same extent on both sides (check_layout), so a pair across a
capacity change fails there by design; that move is accepted once, by ruling, and recorded with its cause.
RODATA is the AAC rodata slot, both models (the 23,530 B vendor payload plus its 2 B internal alignment).

Historical proofs keep their own literals on purpose, because they check frozen inputs from before R9:
check_aacout_layout.py (the retired vendor payload, 43,396 B), check_touchquiz_aac.py, check_touchui_dv8q.py and
test_touch_sampler_owner.py.
"""
TEXT = {'o3ds': 80260, 'n3ds': 59780}
TEXT_RETIRED = (43396,)
TEXT_KNOWN = tuple(sorted(set(TEXT.values()) | set(TEXT_RETIRED)))
RODATA = 23532
