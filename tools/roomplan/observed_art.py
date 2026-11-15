"""Reviewed numeric own-art supplements. New pairs require a receipt, two-store prices and scene identities.

Dates are review dates: these archived diagnostics carry app-relative time, not a wall-clock date.
Only the named data files are qualified; each object's constant stores are resolved through that store's atlas.
"""
DATA_SHA256 = frozenset((
    'b718f8223a5bb31979ffeed10be6140c857b882fc0d0462b89d6287ae38c81c7',
    '946c738c6d6182f683431320a0e32470bc3deb50f3e8887e61998df0c4e3abc8',
))

# (room, directly placed object): public diagnostic/review provenance, never game text or asset names.
OBSERVED_OWN_ART = {
    (53, 951): {
        'evidence': 'observed exact',
        'review_date': '2026-11-09',
        'build': 'd3aeb325f+aot4n',
        'receipt': 'playtest 2 console log, lines 7659-7666',
    },
    (96, 951): {
        'evidence': 'static + likely historical',
        'review_date': '2026-11-09',
        'build': 'cfc178dfd (static audit); historical build not recorded in case 11',
        'receipt': 'tile-miss and plan-gap review notes (same object and missing tiles)',
    },
}
