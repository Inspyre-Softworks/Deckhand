"""Windows Hello RSA wrapping through the Microsoft Passport CNG provider.

No software-provider/DPAPI fallback. Hello prompts belong to the OS. This
backend must be exercised on the target Windows/Hello configuration before
trusting it with a real credential; native calls are isolated for testing.
"""
import ctypes as C
from contextlib import contextmanager
import sys


class HelloError(RuntimeError):
    pass


def current_user_sid():
    """Read the current process token SID without inspecting credentials."""
    from ctypes import wintypes as W
    kernel = C.WinDLL("kernel32", use_last_error=True)
    security = C.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree.restype = C.c_void_p
    security.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    security.OpenProcessToken.restype = W.BOOL
    security.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    security.GetTokenInformation.restype = W.BOOL
    security.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(C.c_wchar_p)]
    security.ConvertSidToStringSidW.restype = W.BOOL
    token = W.HANDLE()
    text = C.c_wchar_p()
    try:
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, C.byref(token)):
            raise HelloError("Windows Hello could not read the current user identity.")
        needed = W.DWORD()
        security.GetTokenInformation(token, 1, None, 0, C.byref(needed))
        if not needed.value:
            raise HelloError("Windows Hello could not determine the user SID size.")
        buffer = C.create_string_buffer(needed.value)
        if not security.GetTokenInformation(token, 1, buffer, needed.value, C.byref(needed)):
            raise HelloError("Windows Hello could not read the user SID.")
        sid = C.cast(buffer, C.POINTER(C.c_void_p))[0]
        if not security.ConvertSidToStringSidW(sid, C.byref(text)):
            raise HelloError("Windows Hello could not format the user SID.")
        return text.value
    finally:
        if text:
            kernel.LocalFree(C.cast(text, C.c_void_p))
        if token:
            kernel.CloseHandle(token)


def passport_key_name(sid, name):
    # Passport requires SID//domain/subdomain/name, not an arbitrary CNG name.
    return f"{sid}//Deckhand/credentials/{name}"


class Hello:
    def __init__(self):
        if sys.platform != "win32":
            raise HelloError("Windows Hello is only available on Windows.")
        self.dll = C.WinDLL("ncrypt.dll")
        self.sid = current_user_sid()
        H, D, P, W = C.c_size_t, C.c_ulong, C.c_void_p, C.c_wchar_p
        signatures = {
            "NCryptOpenStorageProvider": [C.POINTER(H), W, D],
            "NCryptCreatePersistedKey": [H, C.POINTER(H), W, W, D, D],
            "NCryptOpenKey": [H, C.POINTER(H), W, D, D],
            "NCryptSetProperty": [H, W, P, D, D],
            "NCryptGetProperty": [H, W, P, D, C.POINTER(D), D],
            "NCryptFinalizeKey": [H, D], "NCryptFreeObject": [H],
            "NCryptDeleteKey": [H, D],
            "NCryptEncrypt": [H, P, D, P, P, D, C.POINTER(D), D],
            "NCryptDecrypt": [H, P, D, P, P, D, C.POINTER(D), D],
        }
        for name, args in signatures.items():
            fn = getattr(self.dll, name)
            fn.argtypes, fn.restype = args, C.c_long

    def call(self, name, *args):
        status = getattr(self.dll, name)(*args)
        if status:
            detail = f" ({args[1]})" if name in ("NCryptSetProperty", "NCryptGetProperty") else ""
            raise HelloError(f"Windows Hello {name}{detail} failed (0x{status & 0xffffffff:08x}). No fallback was used.")

    @contextmanager
    def key(self, name, create=False):
        name = passport_key_name(self.sid, name)
        provider, key = C.c_size_t(), C.c_size_t()
        created = False
        try:
            self.call("NCryptOpenStorageProvider", C.byref(provider), "Microsoft Passport Key Storage Provider", 0)
            if create:
                self.call("NCryptCreatePersistedKey", provider, C.byref(key), "RSA", name, 0, 0)
                created = True
                size = C.c_ulong(2048)
                self.call("NCryptSetProperty", key, "Length", C.byref(size), C.sizeof(size), 0)
                usage = C.c_ulong(1)  # NCRYPT_ALLOW_DECRYPT_FLAG
                self.call("NCryptSetProperty", key, "Key Usage", C.byref(usage), C.sizeof(usage), 0)
                # Passport-specific auth-mandatory cache policy. Unsupported
                # systems must fail rather than silently allow cached consent.
                mandatory = C.c_ulong(1)
                self.call("NCryptSetProperty", key, "NgcCacheType", C.byref(mandatory), C.sizeof(mandatory), 0)
                self.call("NCryptFinalizeKey", key, 0)
            else:
                self.call("NCryptOpenKey", provider, C.byref(key), name, 0, 0)
            cache_type, length = C.c_ulong(), C.c_ulong()
            self.call("NCryptGetProperty", key, "NgcCacheType", C.byref(cache_type), C.sizeof(cache_type), C.byref(length), 0)
            if cache_type.value != 1:
                raise HelloError("Windows Hello key does not require authentication. Refusing to unlock.")
            context = C.create_unicode_buffer("Unlock your NationStates credential for Deckhand")
            self.call("NCryptSetProperty", key, "Use Context", context, C.sizeof(context), 0)
            yield key
        except Exception:
            if created and key.value:
                self.dll.NCryptDeleteKey(key, 0)
                key.value = 0
            raise
        finally:
            if key.value:
                self.dll.NCryptFreeObject(key)
            if provider.value:
                self.dll.NCryptFreeObject(provider)

    def crypt(self, name, payload, *, decrypt=False, create=False):
        with self.key(name, create=create) as key:
            source = C.create_string_buffer(payload)
            # RSA-2048 output or unwrapped AES-256 key fits in 256 bytes.
            target = C.create_string_buffer(256)
            count = C.c_ulong()
            self.call("NCryptDecrypt" if decrypt else "NCryptEncrypt", key,
                source, len(payload), None, target, len(target), C.byref(count), 2)
            return target.raw[:count.value]

    def delete(self, name):
        name = passport_key_name(self.sid, name)
        # Explicitly delete and release the provider; DeleteKey consumes key.
        provider, key = C.c_size_t(), C.c_size_t()
        try:
            self.call("NCryptOpenStorageProvider", C.byref(provider), "Microsoft Passport Key Storage Provider", 0)
            self.call("NCryptOpenKey", provider, C.byref(key), name, 0, 0)
            self.call("NCryptDeleteKey", key, 0)
            key.value = 0
        finally:
            if key.value:
                self.dll.NCryptFreeObject(key)
            if provider.value:
                self.dll.NCryptFreeObject(provider)
