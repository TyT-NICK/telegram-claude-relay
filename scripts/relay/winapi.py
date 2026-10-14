"""The few Windows API calls tg-relay needs, through ctypes (Windows only)."""

import ctypes
import time
from ctypes import wintypes

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5
CF_UNICODETEXT = 13

user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = (wintypes.UINT,)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds():
    """Seconds since the last keyboard or mouse input in this session, or None."""
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    # Both counters are milliseconds since boot and wrap after 49.7 days
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def pid_alive(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means the process exists but belongs to someone else
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def clipboard_text():
    """Text on the clipboard, or None if there is none or the clipboard stays busy."""
    for _ in range(10):  # another program may hold the clipboard for a moment
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
