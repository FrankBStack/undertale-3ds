"""Own host contract for the production cursor; no game data or 3DS build.

Copies the three production cursor files unchanged into a private harness with
minimal public type/array shims. Run only when host compilation/execution is
authorized. This exercises traversal and membership, not collision geometry.
"""
import os
from pathlib import Path
import shutil
import subprocess

SHIM = r'''
#ifndef PARITY_CURSOR_SHIM_H
#define PARITY_CURSOR_SHIM_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#define nullptr NULL
typedef struct { size_t length, capacity; } Header;
static inline Header* header(const void* p) { return ((Header*)p)-1; }
static inline void resize_array(void** p, size_t width, size_t length) {
    size_t cap = *p ? header(*p)->capacity : 0;
    if (length > cap) {
        size_t capacity = length + 16;
        Header* h = realloc(*p ? header(*p) : NULL, sizeof(Header)+width*capacity);
        assert(h); h->capacity=capacity; *p=h+1;
    }
    if (*p) header(*p)->length=length;
}
#define arrlen(p) ((p) ? (ptrdiff_t)header(p)->length : 0)
#define arrsetlen(p,n) resize_array((void**)&(p), sizeof(*(p)), (size_t)(n))
#define arrfree(p) do { if(p) free(header(p)); (p)=NULL; } while(0)
typedef struct { int32_t targetObjectIndex, codeId; } FlattenedCollisionEvent;
typedef struct { uint32_t eventCount; FlattenedCollisionEvent* events; } FlattenedCollisionEventList;
typedef struct { bool active; void* physicsBody; int32_t objectIndex, instanceId; } Instance;
typedef struct { Instance** instanceSnapshots; Instance*** instancesByExactObject;
                 FlattenedCollisionEventList* flattenedCollisionEvents; } Runner;
#endif
'''


def main():
    root=Path(__file__).resolve().parents[2]
    out=root/'scratch/parity-collision-cursor-host'
    out.mkdir(parents=True,exist_ok=True)
    for name in ('z_utlife_collision.c','z_utlife_collision_membership.c','z_utlife_collision.h'):
        shutil.copyfile(root/'engine/src'/name,out/name)
    (out/'runner.h').write_text(SHIM,encoding='utf-8')
    for name in ('data_win.h','instance.h','string_compat.h'):
        (out/name).write_text('#include "runner.h"\n',encoding='utf-8')
    env=dict(os.environ)
    ucrt=Path('C:/msys64/ucrt64/bin')
    if ucrt.is_dir(): env['PATH']=str(ucrt)+os.pathsep+env['PATH']
    compiler=shutil.which('gcc',path=env['PATH'])
    assert compiler, 'host gcc required; no tool installation or fallback to a game executable'
    binary=out/'own-cursor-contract.exe'
    subprocess.run([compiler,'-std=gnu2x','-O2','-Wall','-Wextra','-Werror',
        '-DENABLE_WAD16','-I',str(out),str(out/'z_utlife_collision.c'),
        str(out/'z_utlife_collision_membership.c'),
        str(root/'tools/analysis/test_parity_collision_cursor.c'),'-o',str(binary)],
        env=env,stdin=subprocess.DEVNULL,check=True,timeout=60)
    subprocess.run([str(binary)],env=env,stdin=subprocess.DEVNULL,check=True,timeout=10)


if __name__=='__main__': main()
