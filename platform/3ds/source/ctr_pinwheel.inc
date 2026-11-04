// DR New pinwheel renderer; scoped to the original Create/Draw events.
// The Create and Weird Route Draw wrappers scope hooks to one event.
// No hook survives the return to the caller. No constructor or global frame/shader dispatch patch is used.
#include "vm.h"
extern RValue aotx_executeLoop(VMContext*);
typedef RValue (*PinwheelGenerated)(VMContext*);
#define PW_PINWHEEL_TEXT __attribute__((noinline,section(".text.weirdshd_pinwheel_late")))
#define PW_PINWHEEL_RO __attribute__((section(".rodata.weirdshd_pinwheel_in_text")))
#define PW_PINWHEEL_BSS __attribute__((section(".bss.weirdshd_pinwheel_late")))
#define PW_PINWHEEL_HANDLE 0x575000
static RendererVtable pwPinwheelReal PW_PINWHEEL_BSS;
static float pwPinwheelValues[3] PW_PINWHEEL_BSS;
static int32_t pwPinwheelShader PW_PINWHEEL_BSS;
static const char pwPinwheelName[] PW_PINWHEEL_RO="shd_pinwheel";
static const char pwPinwheelUniforms[3][10] PW_PINWHEEL_RO={"BaseAngle","Time","Wavyness"};

// An extra call to the original inline makeColor changed GCC's decisions in
// old callers. Keep identical arithmetic in an isolated late body instead.
static PW_PINWHEEL_TEXT __attribute__((noipa)) CtrColor pwPinwheelColor(uint32_t bgr,float alpha) {
    CtrColor c;
    c.r=(uint8_t)BGR_R(bgr);c.g=(uint8_t)BGR_G(bgr);c.b=(uint8_t)BGR_B(bgr);
    if (0.0f>=alpha) c.a=0;
    else if (alpha>=1.0f) c.a=255;
    else c.a=(uint8_t)(alpha*255.0f+0.5f);
    return c;
}

// Preserve the accepted binary32 coverage arithmetic and exact scalar boundary fallback.
#define PW_SCENE_TEXT PW_PINWHEEL_TEXT __attribute__((optimize("no-fast-math","fp-contract=off")))
#define pwTraceValues pwPinwheelValues
static PW_SCENE_TEXT bool pwSceneVisible(float angle, int x, int y) {
    const float tau=6.28318530717958647692f;
    float direction=atan2f(120.0f-((float)y+.5f),((float)x+.5f)-160.0f);
    direction-=tau*floorf(direction/tau);
    float difference=angle*.017453292519943295f-direction+9.42477796076937971539f;
    difference-=tau*floorf(difference/tau);
    return fabsf(difference-3.14159265358979323846f)>=120.0f*.017453292519943295f;
}

#include "ctr_pinwheel_fast.inc"

#undef pwTraceValues

static PW_PINWHEEL_TEXT void pwPinwheelUniformF(Renderer* renderer,int32_t handle,int32_t count,float a,float b,float c,float d) {
    if (handle>=PW_PINWHEEL_HANDLE && handle<PW_PINWHEEL_HANDLE+3) {
        if (count>0) pwPinwheelValues[handle-PW_PINWHEEL_HANDLE]=a;
    } else pwPinwheelReal.shaderSetUniformF(renderer,handle,count,a,b,c,d);
}
static PW_PINWHEEL_TEXT void pwPinwheelUniformArray(Renderer* renderer,int32_t handle,float* values,uint32_t count) {
    if (handle>=PW_PINWHEEL_HANDLE && handle<PW_PINWHEEL_HANDLE+3) {
        if (count && values) pwPinwheelValues[handle-PW_PINWHEEL_HANDLE]=values[0];
    } else pwPinwheelReal.shaderSetUniformFArray(renderer,handle,values,count);
}
static PW_PINWHEEL_TEXT void pwPinwheelUniformI(Renderer* renderer,int32_t handle,int32_t count,int32_t a,int32_t b,int32_t c,int32_t d) {
    if (handle>=PW_PINWHEEL_HANDLE && handle<PW_PINWHEEL_HANDLE+3) {
        if (count>0) pwPinwheelValues[handle-PW_PINWHEEL_HANDLE]=(float)a;
    } else pwPinwheelReal.shaderSetUniformI(renderer,handle,count,a,b,c,d);
}

static PW_PINWHEEL_TEXT void pwPinwheelDraw(Renderer* renderer,int32_t tpag,float x,float y,float ox,float oy,float sx,float sy,float rotation,uint32_t color,float alpha) {
    CtrRenderer* r=(CtrRenderer*)renderer;
    CtrSurface* src=nullptr;
    if (tpag>=0 && (uint32_t)tpag<renderer->dataWin->tpag.count) {
        int32_t slot=-2-renderer->dataWin->tpag.items[tpag].texturePageId;
        if (slot>=0 && slot<arrlen(r->surfaceSprites) && r->surfaceSprites[slot]) src=getSurface(r,r->surfaceSprites[slot]->surfaceId);
    }
    CtrSurface* dst=getSurface(r,r->boundSurface);
    if (src && dst && src->width==640 && src->height==480 && src->shift==1 &&
        !src->recorded && !src->windowed && !src->spilled && src->tex.width==512 && src->tex.height==256 &&
        dst->width==320 && dst->height==240 && dst->shift==0 && !dst->recorded && !dst->windowed && !dst->spilled &&
        x==0 && y==0 && ox==0 && oy==0 && sx==.5f && sy==.5f && rotation==0 && !renderer->texFilter &&
        r->shaderFx==SHADER_FX_NONE && r->palKind==PAL_NONE) {
        TexturePageItem* item=nullptr;
        CtrPage* page=acquireTpagPage(r,tpag,&item);
        if (page && item->sourceX==0 && item->sourceY==0 && item->sourceWidth==640 && item->sourceHeight==480) {
            flushBatch(r);
            int8_t keep=r->filterOverride;
            r->filterOverride=FILTER_NEAREST;
            pwFastRows(r,&page->tiles[0].tex,pwPinwheelColor(color,alpha));
            flushBatch(r);
            r->filterOverride=keep;
            return;
        }
    }
    pwPinwheelReal.drawSprite(renderer,tpag,x,y,ox,oy,sx,sy,rotation,color,alpha);
    flushBatch(r);
}

static PW_PINWHEEL_TEXT void pwPinwheelReset(Renderer* renderer) {
    flushBatch((CtrRenderer*)renderer);
    renderer->vtable->drawSprite=pwPinwheelReal.drawSprite;
    renderer->vtable->shaderSetUniformF=pwPinwheelReal.shaderSetUniformF;
    renderer->vtable->shaderSetUniformFArray=pwPinwheelReal.shaderSetUniformFArray;
    renderer->vtable->shaderSetUniformI=pwPinwheelReal.shaderSetUniformI;
    pwPinwheelReal.gpuResetShader(renderer);
}
static PW_PINWHEEL_TEXT void pwPinwheelSet(Renderer* renderer,int32_t shader) {
    // Restore before changing shader so an unrelated effect takes its own path.
    renderer->vtable->drawSprite=pwPinwheelReal.drawSprite;
    renderer->vtable->shaderSetUniformF=pwPinwheelReal.shaderSetUniformF;
    renderer->vtable->shaderSetUniformFArray=pwPinwheelReal.shaderSetUniformFArray;
    renderer->vtable->shaderSetUniformI=pwPinwheelReal.shaderSetUniformI;
    pwPinwheelReal.gpuSetShader(renderer,shader);
    if (shader==pwPinwheelShader) {
        renderer->vtable->drawSprite=pwPinwheelDraw;
        renderer->vtable->shaderSetUniformF=pwPinwheelUniformF;
        renderer->vtable->shaderSetUniformFArray=pwPinwheelUniformArray;
        renderer->vtable->shaderSetUniformI=pwPinwheelUniformI;
    }
}
static PW_PINWHEEL_TEXT int32_t pwPinwheelGetUniform(Renderer* renderer,int32_t shader,char* uniform) {
    const char* name=shaderName(renderer,shader);
    if (uniform && name && strcmp(name,pwPinwheelName)==0) {
        pwPinwheelShader=shader;
        renderer->vtable->gpuSetShader=pwPinwheelSet;
        renderer->vtable->gpuResetShader=pwPinwheelReset;
        for (int32_t i=0;i<3;++i) if (strcmp(uniform,pwPinwheelUniforms[i])==0) return PW_PINWHEEL_HANDLE+i;
    }
    return pwPinwheelReal.shaderGetUniform(renderer,shader,uniform);
}


// Runner_reset frees instances without Cleanup, so controller-lifetime hooks
// would leak across that boundary. Event scope needs no reset/destroy hook.
// These measured events do not re-enter themselves or replace the renderer.
PW_PINWHEEL_TEXT RValue CtrPinwheel_event(VMContext* ctx, PinwheelGenerated generated, int32_t phase) {
    Renderer* renderer=ctx->runner->renderer;
    memcpy(&pwPinwheelReal,renderer->vtable,sizeof(pwPinwheelReal));
    if (phase==0) {
        pwPinwheelShader=-1;
        memset(pwPinwheelValues,0,sizeof(pwPinwheelValues));
        renderer->vtable->shaderGetUniform=pwPinwheelGetUniform;
    } else {
        renderer->vtable->gpuSetShader=pwPinwheelSet;
        renderer->vtable->gpuResetShader=pwPinwheelReset;
    }
    // Omission of a weak cold generated body must not omit the game event.
    RValue result=generated ? generated(ctx) : aotx_executeLoop(ctx);
    renderer->vtable->drawSprite=pwPinwheelReal.drawSprite;
    renderer->vtable->shaderSetUniformF=pwPinwheelReal.shaderSetUniformF;
    renderer->vtable->shaderSetUniformFArray=pwPinwheelReal.shaderSetUniformFArray;
    renderer->vtable->shaderSetUniformI=pwPinwheelReal.shaderSetUniformI;
    renderer->vtable->shaderGetUniform=pwPinwheelReal.shaderGetUniform;
    renderer->vtable->gpuSetShader=pwPinwheelReal.gpuSetShader;
    renderer->vtable->gpuResetShader=pwPinwheelReal.gpuResetShader;
    return result;
}
