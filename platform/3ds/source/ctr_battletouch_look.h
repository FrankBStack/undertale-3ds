// battletouch r2's menu look, for touchui's draw hook (runner.c's default sprite draw): the one definition of the
// query's flag values (sonrev13 K2, 11-13). z_battletouch.c includes this and defines both symbols (UNDERTALE
// builds). The hook reads CtrBattletouch_menuHide; only while it is nonzero does it ask CtrBattletouch_menuLook()
// about the instance being drawn (currentInstance), which returns these flags, or 0 for the game's own draw.
#ifndef CTR_BATTLETOUCH_LOOK_H
#define CTR_BATTLETOUCH_LOOK_H

#include <stdint.h>

#define BT_LOOK_HIDE 1u   // CtrBattletouch_menuLook: leave this draw out (the menu SOUL)
#define BT_LOOK_ORANGE 2u // with BT_LOOK_FRAME0: orange ink (plain frame 0, as an unchosen button)
#define BT_LOOK_FRAME0 4u // a button: draw its frame 0 (the icon) instead of the game's frame, in yellow ink

// Touch provenance live and the setting on (z_battletouch.c's H2/D1 comment has the full rule).
extern uint8_t CtrBattletouch_menuHide;
// The look of the instance being drawn: BT_LOOK_HIDE, BT_LOOK_FRAME0, BT_LOOK_FRAME0 | BT_LOOK_ORANGE, or 0. Pure.
uint32_t CtrBattletouch_menuLook(void);

#endif
