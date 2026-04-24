"""Minimal capstone wrapper via ctypes — the nix Python env used in prior
phase5 scripts is gone, but libcapstone.so is installed and accessible via
ctypes from the system Python. Only the bits we need for static Thumb
disassembly are exposed here.
"""
import ctypes
import ctypes.util
import glob
import os

CS_ARCH_ARM = 0
CS_MODE_THUMB = 1 << 4
CS_ERR_OK = 0


def _find_libcapstone():
    # 1. Honour an explicit override.
    env = os.environ.get("LIBCAPSTONE")
    if env and os.path.exists(env):
        return env
    # 2. Standard ctypes lookup (ldconfig / LD_LIBRARY_PATH).
    name = ctypes.util.find_library("capstone")
    if name:
        return name
    # 3. Common FHS paths.
    for cand in (
        "/usr/lib/x86_64-linux-gnu/libcapstone.so.5",
        "/usr/lib/libcapstone.so.5",
        "/usr/local/lib/libcapstone.so.5",
    ):
        if os.path.exists(cand):
            return cand
    # 4. Nix store fallback (this host's setup — glob any matching derivation
    #    instead of pinning a single hash so a GC sweep + rebuild doesn't break).
    for cand in sorted(glob.glob("/nix/store/*capstone*/lib/libcapstone.so.5")):
        return cand
    raise RuntimeError(
        "libcapstone.so not found. Set LIBCAPSTONE=/path/to/libcapstone.so.5 "
        "or install capstone via your system package manager."
    )


_LIB = _find_libcapstone()
_cs = ctypes.CDLL(_LIB)


class _CsInsn(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint),
        ("address", ctypes.c_uint64),
        ("size", ctypes.c_uint16),
        ("bytes", ctypes.c_ubyte * 24),
        ("mnemonic", ctypes.c_char * 32),
        ("op_str", ctypes.c_char * 160),
        ("detail", ctypes.c_void_p),
    ]


_cs.cs_open.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]
_cs.cs_open.restype = ctypes.c_int
_cs.cs_close.argtypes = [ctypes.POINTER(ctypes.c_size_t)]
_cs.cs_close.restype = ctypes.c_int
_cs.cs_disasm.argtypes = [
    ctypes.c_size_t,
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.c_uint64,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.POINTER(_CsInsn)),
]
_cs.cs_disasm.restype = ctypes.c_size_t
_cs.cs_free.argtypes = [ctypes.POINTER(_CsInsn), ctypes.c_size_t]


class Insn:
    __slots__ = ("address", "size", "mnemonic", "op_str", "bytes")

    def __init__(self, i):
        self.address = i.address
        self.size = i.size
        self.mnemonic = i.mnemonic.decode("ascii", "replace")
        self.op_str = i.op_str.decode("ascii", "replace")
        self.bytes = bytes(i.bytes[: i.size])


class Cs:
    def __init__(self, arch=CS_ARCH_ARM, mode=CS_MODE_THUMB):
        self.h = ctypes.c_size_t(0)
        rc = _cs.cs_open(arch, mode, ctypes.byref(self.h))
        if rc != CS_ERR_OK:
            raise RuntimeError(f"cs_open failed rc={rc}")

    def __del__(self):
        try:
            _cs.cs_close(ctypes.byref(self.h))
        except Exception:
            pass

    def disasm(self, data, addr, count=0):
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
        arr = ctypes.POINTER(_CsInsn)()
        n = _cs.cs_disasm(self.h, buf, len(data), addr, count, ctypes.byref(arr))
        out = [Insn(arr[i]) for i in range(n)]
        if n:
            _cs.cs_free(arr, n)
        return out


if __name__ == "__main__":
    md = Cs()
    for ins in md.disasm(b"\x70\x47", 0):
        print(f"0x{ins.address:X}: {ins.mnemonic} {ins.op_str}")
