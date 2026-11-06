#pragma once

// Logs each step of the HOME Menu and sleep transitions (see ctr_apt_trace.c).
// Call once the renderer and audio system exist.
void CtrAptTrace_init(void);

// Signal the heartbeat workers to stop before closing the log at exit.
void CtrAptTrace_stop(void);

// Called only by the single exit owner before libctru's _exit/heap teardown.
// Join each worker for at most four seconds; on failure end the mapped process.
void CtrAptTrace_exit(int status) __attribute__((noreturn));
