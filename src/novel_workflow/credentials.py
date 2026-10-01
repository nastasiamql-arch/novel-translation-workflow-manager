"""Current-user Windows DPAPI encryption with no plaintext fallback."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import tempfile


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(raw, decrypt=False):
    if os.name != "nt": raise ValueError("Secure key storage requires Windows DPAPI")
    buffer = ctypes.create_string_buffer(raw)
    source = _Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError("Windows could not access the encrypted API key")
    try: return ctypes.string_at(result.data, result.size)
    finally: kernel32.LocalFree(result.data)


class CredentialStore:
    def __init__(self, root): self.root = Path(root)

    def path(self, profile_id, provider):
        if not re.fullmatch(r"[a-fA-F0-9]{32}", profile_id) or provider not in {"openai", "openai-compatible", "anthropic"}:
            raise ValueError("Invalid credential identifier")
        return self.root / f"{profile_id}-{provider}.bin"

    def get(self, profile_id, provider):
        path = self.path(profile_id, provider)
        return _crypt(path.read_bytes(), decrypt=True).decode("utf-8") if path.exists() else ""

    def set(self, profile_id, provider, key):
        if not key.strip() or any(c in key for c in '\r\n'): raise ValueError("Invalid API key")
        path = self.path(profile_id, provider)
        encrypted = _crypt(key.encode("utf-8"))
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, path)
        finally: Path(name).unlink(missing_ok=True)

    def delete(self, profile_id, provider): self.path(profile_id, provider).unlink(missing_ok=True)
