// SCOURW6-001: submit an open menu's pending edit before common loop teardown.
// main.c's two calls are redirected by compile definitions, keeping its slots.
#if defined(ENABLE_WAD16)
#include "ctr_menu.h"
#include "ctr_renderer.h"
#include <stddef.h>

#define UPD1_CODE __attribute__((noinline, section(".text.late.upd1")))
#define UPD1_BSS __attribute__((section(".bss.late.upd1")))

static struct {
    CtrMenu* menu;
    const CtrDisplaySettings* display;
    CtrDisplaySettings before;
} upd1Options UPD1_BSS;
static const char upd1SettingsPath[] __attribute__((section(".rodata.late.upd1"))) =
    CTRPORT_GAME_DIR "/settings.ini";

void CtrBtnprompt_saveEdits(const CtrDisplaySettings*, const CtrDisplaySettings*, const char*, CtrDisplayCaps);

UPD1_CODE void Upd1_menuOpen(CtrMenu* menu, PrintConsole* console,
                           const CtrDisplaySettings* settings, CtrDisplayCaps caps) {
    // As in main's normal close path, compare against the snapshot from open:
    // a --ini override alone must not become a persistent menu edit.
    upd1Options.before = *settings;
    upd1Options.display = settings;
    upd1Options.menu = menu;
    CtrArgui_menuOpen(menu, console, settings, caps);
}

UPD1_CODE void Upd1_endFlickerProbe(Renderer* renderer) {
    CtrRenderer_endFlickerProbe(renderer);
    CtrMenu* menu = upd1Options.menu;
    upd1Options.menu = NULL;
    if (menu != NULL && menu->open && menu->edited) {
        // Quit chord and false aptMainLoop both converge here, while main's
        // menu/display locals and the settings filesystem are still alive.
        CtrBtnprompt_saveEdits(&upd1Options.before, upd1Options.display,
                              upd1SettingsPath, menu->caps);
        menu->edited = false;
    }
}
#endif
