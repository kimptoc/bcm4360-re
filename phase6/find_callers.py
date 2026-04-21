#!/usr/bin/env python3
"""Map any address to its containing function using the symbol table.

Usage:
    python3 find_callers.py <addr_hex>
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SYMBOLS = os.path.join(HERE, 'wl_function_symbols.txt')

if not os.path.exists(SYMBOLS):
    print(f"Error: {SYMBOLS} not found.")
    sys.exit(1)

funcs = []
with open(SYMBOLS) as f:
    for line in f:
        parts = line.split()
        if len(parts) >= 2:
            try:
                addr = int(parts[0], 16)
                name = parts[1]
                funcs.append((addr, name))
            except ValueError:
                continue

funcs.sort(key=lambda x: x[0])

def find_func(target_addr):
    last = None
    for addr, name in funcs:
        if addr > target_addr:
            return last
        last = (addr, name)
    return last

if len(sys.argv) < 2:
    print("Usage: python3 find_callers.py <addr_hex>")
    sys.exit(1)

try:
    target_addr = int(sys.argv[1], 16)
except ValueError:
    print(f"Invalid address: {sys.argv[1]}")
    sys.exit(1)

func = find_func(target_addr)
if func:
    print(f"0x{target_addr:x} is inside {func[1]} (starts at 0x{func[0]:x})")
else:
    print(f"0x{target_addr:x} not found in any function.")
