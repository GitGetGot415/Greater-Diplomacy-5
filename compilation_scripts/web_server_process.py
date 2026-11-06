"""Keep the Windows web test server and its children in one owned job."""

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess


JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_TERMINATE = 0x0008
ERROR_FILE_NOT_FOUND = 2
CREATE_SUSPENDED = 0x00000004


class _JobLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedJobLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobLimits),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32():
    # Load Windows-only APIs when the Windows launcher uses them.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenJobObjectW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int,
                                     ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = arguments
        function.restype = result
    return kernel


def _job_name(root):
    checkout = os.path.normcase(str(Path(root).resolve())).encode("utf-8")
    return "Local\\GD5-web-test-" + hashlib.sha256(checkout).hexdigest()


def stop_previous_server(root):
    """Stop only a server job previously created for this checkout."""
    kernel = _kernel32()
    job = kernel.OpenJobObjectW(JOB_OBJECT_TERMINATE, False, _job_name(root))
    if not job:
        if ctypes.get_last_error() == ERROR_FILE_NOT_FOUND:
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel.TerminateJobObject(job, 0):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(job)
    return True


class WindowsServerProcess:
    """A server process whose entire tree dies when the launcher closes its job.

    The job handle stays in the launcher. Windows closes that handle even if
    the window closes abruptly and Python cannot execute a finally block.
    """

    def __init__(self, command, cwd):
        # CPython's Windows process API exposes both process and thread handles.
        # Retain the thread until the job owns the suspended process; using
        # Popen here would close that handle before we could safely resume it.
        import _winapi

        self._api = _winapi
        self._kernel = _kernel32()
        self._process = None
        self.returncode = None
        self._job = self._kernel.CreateJobObjectW(None, _job_name(cwd))
        if not self._job:
            raise ctypes.WinError(ctypes.get_last_error())
        thread = None
        try:
            limits = _ExtendedJobLimits()
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self._kernel.SetInformationJobObject(
                    self._job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._process, thread, self.pid, _ = _winapi.CreateProcess(
                None, subprocess.list2cmdline(command), None, None,
                False, CREATE_SUSPENDED, None, str(cwd), subprocess.STARTUPINFO(),
            )
            if not self._kernel.AssignProcessToJobObject(self._job, self._process):
                raise ctypes.WinError(ctypes.get_last_error())
            if self._kernel.ResumeThread(thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            if self._process is not None:
                _winapi.TerminateProcess(self._process, 1)
            self.close()
            raise
        finally:
            if thread is not None:
                _winapi.CloseHandle(thread)

    def poll(self):
        if self.returncode is None and self._api.WaitForSingleObject(
                self._process, 0) == self._api.WAIT_OBJECT_0:
            self.returncode = self._api.GetExitCodeProcess(self._process)
        return self.returncode

    def wait(self):
        # A bounded native wait lets Python handle Ctrl+C on its main thread.
        while self.poll() is None:
            self._api.WaitForSingleObject(self._process, 100)
        return self.returncode

    def close(self):
        if self._job is not None:
            self._kernel.CloseHandle(self._job)
            self._job = None
        if self._process is not None:
            try:
                self.wait()
            finally:
                self._api.CloseHandle(self._process)
                self._process = None
