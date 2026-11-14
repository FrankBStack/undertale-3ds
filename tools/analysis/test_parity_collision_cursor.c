/* Own synthetic identities/events only. Links the production cursor sources. */
#include "z_utlife_collision.h"
#include <stdio.h>

static Runner runner;
static Instance a={true,NULL,0,11}, b={true,NULL,0,22}, born={true,NULL,0,33};
static FlattenedCollisionEvent events[]={{1,101},{1,102}};
static FlattenedCollisionEventList lists[]={{2,events}};
static Instance** buckets[1];

static UtlifeCollisionCursor reset(bool compat) {
    arrfree(runner.instanceSnapshots); arrfree(buckets[0]);
    a.active=b.active=born.active=true;
    a.objectIndex=b.objectIndex=born.objectIndex=0;
    a.physicsBody=b.physicsBody=born.physicsBody=NULL;
    events[0].codeId=101; events[1].codeId=102;
    arrsetlen(buckets[0],2); buckets[0][0]=&a; buckets[0][1]=&b;
    arrsetlen(runner.instanceSnapshots,2);
    memcpy(runner.instanceSnapshots,buckets[0],2*sizeof(Instance*));
    runner.instancesByExactObject=buckets;
    runner.flattenedCollisionEvents=lists;
    return (UtlifeCollisionCursor){.count=2,.object=0,.list=lists,.eventFirst=compat};
}

static void take(UtlifeCollisionCursor* c,int id,int code) {
    assert(Utlife_nextCollision(&runner,c));
    assert(c->self->instanceId==id && c->evt->codeId==code);
}

int main(void) {
    /* Event-first versus self-first is a discriminating order oracle. */
    UtlifeCollisionCursor c=reset(true);
    take(&c,11,101); take(&c,22,101); take(&c,11,102); take(&c,22,102);
    assert(!Utlife_nextCollision(&runner,&c));
    c=reset(false);
    take(&c,11,101); take(&c,11,102); take(&c,22,101); take(&c,22,102);
    assert(!Utlife_nextCollision(&runner,&c));

    /* New births cannot enter an event in progress, but enter the next one. */
    c=reset(true); take(&c,11,101);
    arrsetlen(buckets[0],3); buckets[0][2]=&born;
    take(&c,22,101); take(&c,11,102); take(&c,22,102); take(&c,33,102);
    assert(!Utlife_nextCollision(&runner,&c));

    /* Fallback snapshots exclude that birth for the whole self-first pass. */
    c=reset(false); take(&c,11,101);
    arrsetlen(buckets[0],3); buckets[0][2]=&born;
    take(&c,11,102); take(&c,22,101); take(&c,22,102);
    assert(!Utlife_nextCollision(&runner,&c));

    /* Callback destruction and class changes exclude old-class callbacks. */
    c=reset(true); take(&c,11,101); b.active=false;
    take(&c,11,102); assert(!Utlife_nextCollision(&runner,&c));
    c=reset(true); take(&c,11,101); b.objectIndex=7;
    take(&c,11,102); assert(!Utlife_nextCollision(&runner,&c));
    c=reset(true); take(&c,11,101); a.objectIndex=7;
    take(&c,22,101); take(&c,22,102); assert(!Utlife_nextCollision(&runner,&c));

    /* Physics and absent event-code guards remain active. */
    c=reset(true); a.physicsBody=&a;
    take(&c,22,101); take(&c,22,102); assert(!Utlife_nextCollision(&runner,&c));
    c=reset(true); events[0].codeId=-1;
    take(&c,11,102); take(&c,22,102); assert(!Utlife_nextCollision(&runner,&c));

    /* Snapshot storage may grow during callbacks: retain indices, not pointers. */
    c=reset(true); take(&c,11,101);
    arrsetlen(runner.instanceSnapshots,128);
    take(&c,22,101); take(&c,11,102); take(&c,22,102);
    assert(!Utlife_nextCollision(&runner,&c));

    /* A hit-epoch change cannot replace compatibility's frozen target list. */
    c=reset(true); take(&c,11,101);
    assert(c.eventStart && Utlife_collisionTargetsNeedSnapshot(&c,1,1,0,0));
    take(&c,22,101);
    assert(!c.eventStart && !Utlife_collisionTargetsNeedSnapshot(&c,1,1,0,1));
    assert(Utlife_collisionTargetsNeedSnapshot(&c,2,1,0,0));
    take(&c,11,102);
    assert(c.eventStart && Utlife_collisionTargetsNeedSnapshot(&c,1,1,0,0));
    c=reset(false); take(&c,11,101);
    assert(!Utlife_collisionTargetsNeedSnapshot(&c,1,1,0,0));
    assert(Utlife_collisionTargetsNeedSnapshot(&c,1,1,0,1));

    c=reset(true); arrsetlen(buckets[0],0);
    take(&c,11,101); take(&c,22,101); assert(!Utlife_nextCollision(&runner,&c));
    arrfree(runner.instanceSnapshots); arrfree(buckets[0]);
    puts("PARITY cursor: 12 synthetic contracts; production helpers; no game data");
    return 0;
}
