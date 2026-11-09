"""
Unpacker for the YU-NO Windows (Elf Classics / AI5WIN) .ARC archives.
Cross-platform rewrite of kingshriek's arcunpack.py (no DLL needed).

Archive layout:
    u32  file count
    N x  { 20s name (xor 0x03), u32 size (xor 0x33656755), u32 offset (xor 0x68820811) }
Entries with extension .MES/.A6/.S4/.BIN are LZSS-compressed (same LZSS as the
Saturn ABZ containers: dict 0x1000, start 0xFEE, min match 3).

Usage:
    python win_arc.py list   <file.arc>
    python win_arc.py unpack <file.arc> <out_dir> [glob]
"""
import fnmatch
import os
import struct
import sys

COMP_EXT = ('.MES', '.A6', '.S4', '.BIN')
DICT_SIZE = 0x1000
DICT_START = 0xFEE


def lzss_decompress(payload):
    out = bytearray()
    dictbuf = bytearray(DICT_SIZE)
    dpos = DICT_START
    i = 0
    n = len(payload)
    while i < n:
        ctrl = payload[i]
        i += 1
        for bit in range(8):
            if ctrl & (1 << bit):
                if i >= n:
                    return bytes(out)
                b = payload[i]
                i += 1
                out.append(b)
                dictbuf[dpos] = b
                dpos = (dpos + 1) & (DICT_SIZE - 1)
            else:
                if i + 1 >= n:
                    return bytes(out)
                d1 = payload[i]
                d2 = payload[i + 1]
                i += 2
                length = (d2 & 0x0F) + 3
                idx = ((d2 & 0xF0) << 4) | d1
                for k in range(length):
                    b = dictbuf[(idx + k) & (DICT_SIZE - 1)]
                    out.append(b)
                    dictbuf[dpos] = b
                    dpos = (dpos + 1) & (DICT_SIZE - 1)
    return bytes(out)


def read_entries(f):
    nfiles = struct.unpack('<I', f.read(4))[0]
    entries = []
    for _ in range(nfiles):
        raw_name, size, offset = struct.unpack('<20sII', f.read(28))
        name = bytes(b ^ 3 for b in raw_name).rstrip(b'\x00').decode('ascii')
        entries.append((name, offset ^ 0x68820811, size ^ 0x33656755))
    return entries


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, arc = sys.argv[1], sys.argv[2]
    with open(arc, 'rb') as f:
        entries = read_entries(f)
        if cmd == 'list':
            for i, (name, off, size) in enumerate(entries):
                print(f'{i:5d}  {name:<16} off=0x{off:08x} size={size}')
            print(f'{len(entries)} entries')
            return
        out_dir = sys.argv[3]
        pattern = sys.argv[4] if len(sys.argv) > 4 else '*'
        os.makedirs(out_dir, exist_ok=True)
        n = 0
        for name, off, size in entries:
            if not fnmatch.fnmatch(name, pattern):
                continue
            f.seek(off)
            data = f.read(size)
            if os.path.splitext(name)[1].upper() in COMP_EXT:
                data = lzss_decompress(data)
            with open(os.path.join(out_dir, name), 'wb') as o:
                o.write(data)
            n += 1
        print(f'Unpacked {n} files to {out_dir}')


if __name__ == '__main__':
    main()
