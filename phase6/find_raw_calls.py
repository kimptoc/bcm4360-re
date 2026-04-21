import sys
import struct

def find_calls(filename, target_addr):
    with open(filename, 'rb') as f:
        data = f.read()
    
    # Target address is 0x12543. Relative offset is target - (call_site_addr + 5)
    # So call_site_addr + 5 + offset = target
    # We search for e8 XX XX XX XX
    
    # We don't know the load address but usually for .ko it's 0-based in objdump
    # Let's assume the file offset matches the objdump address for simplicity, 
    # which is often true for the .text section in simple ELF files.
    # However, to be safe, let's just scan the whole thing.
    
    results = []
    for i in range(len(data) - 5):
        if data[i] == 0xe8:
            offset = struct.unpack('<i', data[i+1:i+5])[0]
            # Potential target address if i is the address of the e8 byte
            potential_target = i + 5 + offset
            if potential_target == target_addr:
                results.append(i)
    return results

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 find_raw_calls.py <file> <target_addr_hex>")
        sys.exit(1)
    
    filename = sys.argv[1]
    target = int(sys.argv[2], 16)
    found = find_calls(filename, target)
    for addr in found:
        print(f"Found call to 0x{target:x} at 0x{addr:x}")
