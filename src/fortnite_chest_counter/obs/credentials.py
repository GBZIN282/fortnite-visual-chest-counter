"""
The OBS WebSocket password, kept in Windows Credential Manager (Control Panel > Credential Manager > Windows
Credentials, entry "Fortnite Visual Chest Counter/OBS WebSocket"). Windows encrypts it for the signed-in user.

It is never written to config.toml, the logs, the diagnostics report or the app folder, so a zipped app folder or a
support report can never contain it. "Forget password" in the app deletes the entry. Standard library only (ctypes).
"""

import ctypes
from ctypes import wintypes

TARGET = "Fortnite Visual Chest Counter/OBS WebSocket"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2         # this PC and Windows user (not roamed to other PCs)
_ERROR_NOT_FOUND = 1168
MAX_PASSWORD = 512                      # characters (Windows allows 2,560 bytes = 1,280 UTF-16 characters)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR)]


def _advapi():
    try:
        api = ctypes.WinDLL("advapi32", use_last_error=True)
    except (AttributeError, OSError):
        return None
    api.CredWriteW.argtypes, api.CredWriteW.restype = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD], wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes, api.CredDeleteW.restype = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD], wintypes.BOOL
    api.CredFree.argtypes, api.CredFree.restype = [ctypes.c_void_p], None
    return api


def available():
    return _advapi() is not None


def save_password(password, target=TARGET):
    """Store (or replace) the password. An empty password deletes the entry. Raises OSError if Windows refuses."""
    if not password:
        forget_password(target)
        return
    if len(password) > MAX_PASSWORD:
        raise ValueError("password too long")
    api = _advapi()
    if api is None:
        raise OSError("Windows Credential Manager is not available")
    blob = password.encode("utf-16-le")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _CREDENTIALW(Flags=0, Type=_CRED_TYPE_GENERIC, TargetName=target, Comment="OBS WebSocket password",
                        CredentialBlobSize=len(blob), CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
                        Persist=_CRED_PERSIST_LOCAL_MACHINE, UserName="obs-websocket")
    if not api.CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def load_password(target=TARGET):
    """The saved password, or "" if there is none (or Credential Manager is unavailable)."""
    api = _advapi()
    if api is None:
        return ""
    pointer = ctypes.POINTER(_CREDENTIALW)()
    if not api.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        return ""
    try:
        cred = pointer.contents
        return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-16-le", errors="replace")
    finally:
        api.CredFree(pointer)


def forget_password(target=TARGET):
    """Delete the saved password (no error if there is none)."""
    api = _advapi()
    if api is None:
        return
    if not api.CredDeleteW(target, _CRED_TYPE_GENERIC, 0) and ctypes.get_last_error() != _ERROR_NOT_FOUND:
        raise ctypes.WinError(ctypes.get_last_error())


def has_password(target=TARGET):
    return bool(load_password(target))
