"""Player regression gate: host helpers/wiring plus frozen and reviewed ELF scope.

Run after serial Release builds. Each directory contains undertale-o3ds and
undertale-n3ds/undertale-3ds.elf. The frozen baseline is fa0612c9d; the optional
reviewed player baseline is 31418d481. Reports contain public binary hashes only.
"""
from pathlib import Path
import argparse,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--player',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    # Resolve user paths before subprocesses run from the source root.
    args.frozen=args.frozen.resolve();args.candidate=args.candidate.resolve()
    args.out=args.out.resolve()
    if args.player is not None:args.player=args.player.resolve()
    def run(*command):
        subprocess.run([sys.executable,'-I',*map(str,command)],cwd=ROOT,
                       check=True,stdin=subprocess.DEVNULL,timeout=240)
    run(ROOT/'tools/release/test_dlgtop_player.py')
    run(ROOT/'tools/buildcache/test_loadgame_compile.py')
    for model in ('o3ds','n3ds'):
        target='undertale-'+model
        for label,base in (('frozen',args.frozen),('player',args.player)):
            if base is None:continue
            flags=['--player-baseline'] if label=='player' else []
            run(ROOT/'tools/analysis/check_dlgtop_ut_layout.py',
                base/target/'undertale-3ds.elf',args.candidate/target/'undertale-3ds.elf',
                '--game','undertale','--model',model,'--out',args.out/label,*flags)
    print('PASS: actual carry, source wiring, adapter, Old/New exact ELF scope',flush=True)

if __name__=='__main__':main()
