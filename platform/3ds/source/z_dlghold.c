// names only: menu object identifiers used to end a dialogue replay hold.
// No game logic runs here; these are non-owning reads of the existing menu state.
#include "ctr_dialogue.h"

#include <string.h>

#include "vm.h"

#define DH_CODE __attribute__((section(".text.late.dlghold"), noinline))
#define DH_RODATA __attribute__((section(".rodata.late.dlghold")))

#if defined(ENABLE_WAD16)
static const char dhInteract[] DH_RODATA = "interact";

bool __real_CtrDialogue_holdAllowed(const CtrDialoguePolicy* policy, Runner* runner);

DH_CODE bool __wrap_CtrDialogue_holdAllowed(const CtrDialoguePolicy* policy, Runner* runner) {
    if (!__real_CtrDialogue_holdAllowed(policy, runner)) return false;
    // UNDERTALE's overworld controller draws save, item and box menus while
    // interact == 5. The savepoint itself persists during genuine dialogue.
    VMContext* ctx = runner->vmContext;
    RValue interact = VM_structGetVariableByVarName(ctx, ctx->globalScopeInstance, dhInteract, -1);
    // The original predicate has already rejected every non-numeric type.
    if (interact.type == RVALUE_REAL) return interact.real != 5;
    if (interact.type == RVALUE_INT64) return interact.int64 != 5;
    return interact.int32 != 5;
}
#else
// DELTARUNE New: Crisp art's retained ARM entry (and its veneer+8 relocation guard) is fpsbox's
// (ctr_fpsbox.c, .text.fpsbox75zm_veneer): stage 75zo keeps one shared entry, so none here.
static const char dhMenus[][16] DH_RODATA = {
    "obj_savemenu", "DEVICE_MENU", "obj_custommenu", "obj_fusionmenu",
};

void __real_CtrDialogue_init(CtrDialoguePolicy* policy, const DataWin* dataWin);

DH_CODE void __wrap_CtrDialogue_init(CtrDialoguePolicy* policy, const DataWin* dataWin) {
    __real_CtrDialogue_init(policy, dataWin);
    // Resolve once per game/chapter into the policy's existing spare slots.
    // Both active dialogue and its gap hold then use the same menu blockers.
    for (uint32_t i = 0; dataWin->objt.count > i && policy->blockCount < CTR_DIALOGUE_BLOCK_OBJECTS; i++) {
        const char* name = dataWin->objt.objects[i].name;
        if (name == nullptr) continue;
        for (size_t j = 0; sizeof(dhMenus) / sizeof(dhMenus[0]) > j; j++) {
            if (strcmp(name, dhMenus[j]) != 0) continue;
            policy->blockObjects[policy->blockCount++] = (int32_t) i;
            break;
        }
    }
}
#endif

#if defined(ENABLE_WAD16)
// UNDERTALE must stop showing the redirected picture when its current draws stop.
// Keep the old policy entry linked at its original address for frozen layout.
__attribute__((section(".text.late.dlglinger"), noinline, noipa))
bool CtrDlglinger_noHold(const CtrDialoguePolicy* policy, Runner* runner) {
    (void) policy;
    (void) runner;
    return false;
}
#endif
