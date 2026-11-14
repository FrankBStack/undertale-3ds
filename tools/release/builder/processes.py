"""Console-free Windows children; callers keep piping output to their log."""
import os
import signal
import subprocess
import sys
import threading
import time


def hidden_options(*, group=False):
    if sys.platform != 'win32':
        return {}
    flags = subprocess.CREATE_NO_WINDOW
    if group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return {'creationflags': flags}


CREATE_SUSPENDED = 0x00000004
STOP_SECONDS = 30   # a stopped build must be gone by then, or the builder says it could not stop it (TK-R2)


class StopFailed(OSError):
    """A stop was asked for and the build is not known to have stopped."""


IDLE, RUNNING, STOPPING, RELEASING, RELEASED = 'idle', 'running', 'stopping', 'releasing', 'released'


class ProcessGroup:
    """The build and everything it starts, and nothing else (TK-1).

    Stopping by PID tree (the old /T stop) also stops a stranger whose recorded parent PID matches a build process
    (Windows keeps a dead parent's PID in its children), and killpg on a reaped leader's PID can reach a new group
    that reused it. So on Windows the root starts suspended, joins a job object the builder created, and only
    then runs: every process it starts is in the job, and stop() ends the job. On POSIX the root leads a new
    session (start_new_session), and stop() signals that group only while the leader is unreaped, which keeps
    its PID, and so the group ID, from being reused. A child that is not a real subprocess.Popen (the tests'
    fakes) is never signalled. If the job cannot be set up, the suspended root is killed and the build fails.

    Lifecycle (TK-D6..D8). Every transition happens under self._lock:

        idle --started()--> running --stop()--> stopping
        running | stopping --release()--> releasing --> released(outcome)
        running --release(), nothing alive, no stop asked--> released(None)
        idle --started() fails--> released(outcome)

    release() is the only way out of running or stopping, and with started()'s failure path the only caller of
    close(). Under the lock it asks whether anything may still be alive (on Windows the job's active-process
    count, an unknown count counting as alive; elsewhere an unreaped root). If so, or if a stop was asked for,
    it requests a stop and moves to releasing; the stop is then confirmed outside the lock (job empty, or root
    reaped, within STOP_SECONDS). Then, under the lock again, the outcome is stored, the job handle closed and
    `released` set, in that order. The outcome is None when the build is known to have ended, else why not.
    A stop() that takes the lock before release() decides is confirmed by it; a stop() during releasing joins
    that confirmation; a stop() once released does nothing and returns False, so it never claims that the old
    job was just confirmed. release() never raises.
    """

    def __init__(self):
        self._lock = threading.RLock()  # close() runs while it is held
        self._proc = None
        self._job = None
        self._reaped = False
        self._windows = sys.platform == 'win32'
        self.state = IDLE
        self.stop_error = None      # why a stop request failed (TK-R2)
        self._stop_by = None        # monotonic deadline for a requested stop to finish
        self.outcome = None         # with `released`: None if the build is known to have ended, else why not
        self.close_error = None     # why the job handle would not close; kept apart from the outcome (TK-N1)
        self.released = threading.Event()

    def popen_kwargs(self):
        kw = hidden_options(group=True)
        if self._windows:
            kw['creationflags'] |= CREATE_SUSPENDED
        else:
            kw['start_new_session'] = True
        return kw

    def started(self, proc):
        """Call at once with the child popen_kwargs() made; on Windows it is suspended until this returns."""
        with self._lock:
            self._proc = proc
            if not (self._windows and isinstance(proc, subprocess.Popen)):
                self.state = RUNNING
                return proc
            try:
                self._job = _job_for(proc)
            except BaseException as exc:
                # The job made for it would not close: a note beside the containment error, never instead of it.
                self.close_error = getattr(exc, 'job_close_error', None)
                outcome = None
                try:
                    proc.kill()          # our own handle; the root never ran
                    proc.wait()
                    self._reaped = True
                except BaseException as exc:
                    outcome = 'the suspended build could not be ended (%s)' % exc
                self._finish_locked(outcome)
                raise
            self.state = RUNNING
            return proc

    def wait(self, proc, interval=0.1):
        """proc.wait(), but the reap happens under the lock stop() takes. After a stop, bounded by check()."""
        while True:
            with self._lock:
                rc = proc.poll()
                if rc is not None:
                    self._reaped = True
                    return rc
            self.check()
            time.sleep(interval)

    def wait_stopped(self, proc, interval=0.05):
        """After stop(): return once the whole build has ended (on Windows, its job is empty). Raises StopFailed
        when the stop failed or has not finished in STOP_SECONDS (TK-D4)."""
        if self._windows and self._job is not None:
            while self._job_active():
                self.check()
                time.sleep(interval)
        else:
            self.wait(proc, interval)
        if self.stop_error is not None:
            raise StopFailed(self.stop_error)

    def _job_active(self):
        import ctypes

        class Accounting(ctypes.Structure):     # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
            _fields_ = [(n, ctypes.c_int64) for n in ('user', 'kernel', 'period_user', 'period_kernel')] + [
                (n, ctypes.c_uint32) for n in ('faults', 'total', 'active', 'terminated')]
        info = Accounting()
        with self._lock:
            if self._job is None:
                return 0
            if not _kernel32().QueryInformationJobObject(self._job, 1, ctypes.byref(info), ctypes.sizeof(info),
                                                         None):
                raise StopFailed('QueryInformationJobObject failed (Windows error %d)' % ctypes.get_last_error())
        return info.active

    def check(self):
        """Raise StopFailed once a requested stop is known to have failed, or has not finished in STOP_SECONDS."""
        if self.stop_error is not None:
            raise StopFailed(self.stop_error)
        if self._stop_by is not None and time.monotonic() > self._stop_by:
            raise StopFailed('still running %d s after it was asked to stop' % STOP_SECONDS)

    def stop(self):
        """Ask the build to stop. Returns True when release() will confirm the stop or report that it could not,
        False when there is nothing of ours to stop: not started, a fake, or already released (TK-D6). A failed
        request is kept in stop_error, and check() then reports it."""
        with self._lock:
            return self._stop_locked()

    def _stop_locked(self):
        proc = self._proc
        if self.state not in (RUNNING, STOPPING, RELEASING) or not isinstance(proc, subprocess.Popen):
            return False
        if self._stop_by is None:
            self._stop_by = time.monotonic() + STOP_SECONDS
        if self.state == RELEASING:
            return True              # release() asked already and is confirming it: join that, ask nothing new (TK-D10)
        if self.state == RUNNING:
            self.state = STOPPING
        try:
            if self._windows:
                if self._job is not None:
                    if not _kernel32().TerminateJobObject(self._job, 1):
                        import ctypes
                        self.stop_error = 'TerminateJobObject failed (Windows error %d)' % ctypes.get_last_error()
                        if not self._reaped and proc.returncode is None:
                            proc.kill()  # the root at least, through our own handle; its children may live on
                elif not self._reaped and proc.returncode is None:
                    proc.kill()      # our own process handle, never a PID lookup
            elif not self._reaped and proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass             # the group has already ended
        except OSError as exc:       # killpg, or a kill through our own handle: the stop is not confirmed
            if self.stop_error is None:
                self.stop_error = 'stopping the build failed (%s)' % exc
        return True

    def _may_be_alive_locked(self, proc):
        if not isinstance(proc, subprocess.Popen):
            return False
        if self._windows and self._job is not None:
            try:
                return self._job_active() > 0
            except BaseException:
                return True          # an unknown count counts as alive
        if self._reaped or proc.returncode is not None:
            return False
        try:
            if proc.poll() is not None:  # under the lock, as in wait(): a reap and a killpg never cross
                self._reaped = True
                return False
        except BaseException:
            pass
        return True

    def stop_bound(self):
        return STOP_SECONDS

    def release(self, proc):
        """The one way a build's job is let go (TK-D5..D8); see the class notes. Returns the outcome."""
        try:
            with self._lock:
                if self.state == RELEASED:
                    return self.outcome
                if self.state == IDLE:
                    self._finish_locked(None)
                    return None
                if self._may_be_alive_locked(proc) or self._stop_by is not None:
                    self._stop_locked()
                if self._stop_by is None:     # nothing of ours alive and no stop asked for
                    self._finish_locked(None)
                    return None
                self.state = RELEASING
            try:
                self.wait_stopped(proc)
                outcome = None
            except BaseException as exc:  # StopFailed, or anything else: the stop is not confirmed
                outcome = str(exc) or type(exc).__name__
            with self._lock:
                if outcome is None and self.stop_error is not None:
                    outcome = self.stop_error    # a failed stop request is never dropped from the outcome (TK-D10)
                self._finish_locked(outcome)
                return outcome
        except BaseException as exc:
            with self._lock:
                if self.state != RELEASED:
                    self._finish_locked('releasing the build failed (%s: %s)' % (type(exc).__name__, exc))
                return self.outcome

    def _finish_locked(self, outcome):
        self.outcome = outcome       # stored first: nothing after this can lose it (TK-D7)
        self.state = RELEASED
        try:
            self.close()             # a job without kill-on-close: closing its handle never affects a process
        except BaseException as exc:
            self.close_error = '%s: %s' % (type(exc).__name__, exc)     # kept and shown, never raised (TK-N1)
        finally:
            self.released.set()

    def close(self):
        """Close the job handle. Only _finish_locked() calls it, after the outcome is stored."""
        with self._lock:
            if self._job is not None:
                job, self._job = self._job, None
                if not _kernel32().CloseHandle(job):
                    import ctypes
                    self.close_error = 'CloseHandle failed (Windows error %d)' % ctypes.get_last_error()


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.c_void_p]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _job_for(proc):
    import ctypes
    from ctypes import wintypes
    k = _kernel32()
    job = k.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), 'CreateJobObjectW failed')
    try:
        handle = wintypes.HANDLE(int(proc._handle))
        if not k.AssignProcessToJobObject(job, handle):
            raise OSError(ctypes.get_last_error(), 'AssignProcessToJobObject failed')
        ntdll = ctypes.WinDLL('ntdll')
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        status = ntdll.NtResumeProcess(handle)
        if status != 0:
            k.TerminateJobObject(job, 1)
            raise OSError('NtResumeProcess failed: 0x%08x' % (status & 0xffffffff))
    except BaseException as exc:
        # Any failure after creation closes the job before it is handed out. A close that fails rides on the
        # original error as job_close_error (started() keeps it in close_error); the original is what is raised.
        try:
            note = None if k.CloseHandle(job) else 'CloseHandle failed (Windows error %d)' % ctypes.get_last_error()
        except BaseException as close_exc:
            note = '%s: %s' % (type(close_exc).__name__, close_exc)
        if note is not None:
            try:
                exc.job_close_error = note
            except BaseException:
                pass
        raise
    return job
