#!/usr/bin/env python3
"""Map relocation call-sites to their containing functions.

Usage from phase6/:
    python3 find_callers.py

Symbol file: wl_function_symbols.txt (in same directory).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SYMBOLS = os.path.join(HERE, 'wl_function_symbols.txt')

funcs = []
with open(SYMBOLS) as f:
    for line in f:
        parts = line.split()
        addr = int(parts[0], 16)
        name = parts[1]
        funcs.append((addr, name))

funcs.sort(key=lambda x: x[0])

def find_func(call_addr):
    """Find the function containing the given call address."""
    last = None
    for addr, name in funcs:
        if addr > call_addr:
            return last
        last = (addr, name)
    return last

all_calls = {
    'wlc_bmac_corereset': [0x152ac6, 0x26f64, 0x6605d, 0x66561, 0x66b74, 0x69b1d],
    'wlc_bmac_si_attach': [0x37d77],
    'wlc_bmac_attach': [0x37f8f],
    'wlc_hw_attach': [0x69895],
    'si_attach': [0x66e16, 0x66e8e],
}

for target, addrs in all_calls.items():
    print(f"=== {target} callers ===")
    for addr in sorted(addrs):
        func = find_func(addr)
        if func:
            print(f"  0x{addr:06x} -> {func[1]} (fn_start=0x{func[0]:06x})")
    print()
