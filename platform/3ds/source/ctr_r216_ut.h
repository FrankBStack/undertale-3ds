// R216 (change auditfixe2): the crash-screen and save-guard net (SCOURS4-005's loading-bar halt and paint gate, the
// fatal claim's clock, the save guard, the Rosalina watcher's stop) is UNDERTALE only for 1.0 (a ruling,
// 11-05). DELTARUNE Old's late text has 740 B left and the net needs about 2 KB there, so DELTARUNE builds keep the
// code from before R216, byte for byte (parked for the DELTARUNE round).
// Each line the net changed inside an existing body names both forms: R216_PICK(undertale, deltarune) takes one of
// two names, and R216_UT(...) keeps its text in UNDERTALE only. Either way the line stays one line, so no __LINE__
// of the file moves. The net's own code (appended at each file's end) is under #ifdef ENABLE_WAD16.
#ifndef CTRPORT_CTR_R216_UT_H
#define CTRPORT_CTR_R216_UT_H

#ifdef ENABLE_WAD16
#define R216_PICK(undertale, deltarune) undertale
#define R216_UT(...) __VA_ARGS__
#else
#define R216_PICK(undertale, deltarune) deltarune
#define R216_UT(...)
#endif

#endif
