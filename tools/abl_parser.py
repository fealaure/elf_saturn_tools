"""
Parser for the Elf 'ABLINK' archive format used by YU-NO Saturn.

Header (16 bytes):
    0x00  6  ASCII 'ABLINK'
    0x06  2  version (02 01)
    0x08  4  unknown (size/checksum?)
    0x0C  4  entry count (big-endian uint32)

Each entry (12 bytes):
    0x00  8  name, ASCII, null-padded
    0x08  1  type/category (0x01=CG, 0x02=script, 0x03=frame,
                            0x06=UI image, 0x08=font, 0x0A=audio)
    0x09  3  offset (big-endian uint24)

The offset's unit is unknown — we test 2048-byte sectors first.

Usage:
    python abl_parser.py <file.abl>           # list entries
    python abl_parser.py <file.abl> <name> <out.bin>   # dump one entry's raw bytes
"""
import os
import sys
import struct


def parse_header(data):
    if data[:6] != b'ABLINK':
        raise ValueError(f'Bad magic: {data[:6]!r}')
    version = (data[6], data[7])
    unk = struct.unpack('>I', data[8:12])[0]
    count = struct.unpack('>I', data[12:16])[0]
    return version, unk, count


def parse_entries(data, count):
    entries = []
    for i in range(count):
        off = 16 + i * 12
        rec = data[off:off + 12]
        name = rec[:8].rstrip(b'\x00').decode('ascii', errors='replace')
        type_code = rec[8]
        sect_offset = (rec[9] << 16) | (rec[10] << 8) | rec[11]
        entries.append({
            'name': name,
            'type': type_code,
            'sector': sect_offset,
            'raw_offset_2048': sect_offset * 2048,
        })
    return entries


def compute_sizes(entries, file_len):
    """Sort by sector, infer each entry's byte length from the next entry's start."""
    indexed = sorted(enumerate(entries), key=lambda x: x[1]['sector'])
    for k, (orig_idx, e) in enumerate(indexed):
        if k + 1 < len(indexed):
            next_sector = indexed[k + 1][1]['sector']
            byte_size = (next_sector - e['sector']) * 2048
        else:
            byte_size = file_len - e['raw_offset_2048']
        entries[orig_idx]['byte_size_guess'] = byte_size
    return entries


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    abl_path = sys.argv[1]
    with open(abl_path, 'rb') as f:
        data = f.read()
    version, unk, count = parse_header(data)
    entries = parse_entries(data, count)
    entries = compute_sizes(entries, len(data))

    print(f'File:    {abl_path}')
    print(f'Size:    {len(data)} bytes')
    print(f'Version: {version}  Header[8..12]={unk:#010x}  Entries: {count}')
    print('---')
    print(f'{"#":>4}  {"NAME":<10}  {"TYPE":>4}  {"SECTOR":>8}  {"OFFSET":>10}  {"~SIZE":>10}')
    for i, e in enumerate(entries):
        print(f'{i:>4}  {e["name"]:<10}  0x{e["type"]:02x}  {e["sector"]:>8}  '
              f'{e["raw_offset_2048"]:>10}  {e["byte_size_guess"]:>10}')

    # Dump one entry as raw bytes
    if len(sys.argv) == 4:
        target_name = sys.argv[2].upper()
        out_path = sys.argv[3]
        for e in entries:
            if e['name'].upper() == target_name:
                start = e['raw_offset_2048']
                end = start + e['byte_size_guess']
                with open(out_path, 'wb') as g:
                    g.write(data[start:end])
                print(f'\nDumped {e["name"]}: {end - start} bytes -> {out_path}')
                return
        print(f'\nEntry {target_name!r} not found.')


if __name__ == '__main__':
    main()
