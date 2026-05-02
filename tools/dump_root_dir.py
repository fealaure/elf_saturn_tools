"""Dump raw bytes and parsed entries of the root directory for debugging."""
import struct, sys

SECTOR_RAW = 2352
SECTOR_DATA = 2048
SECTOR_HEADER = 16

def read_sector(fp, lba):
    fp.seek(lba * SECTOR_RAW + SECTOR_HEADER)
    return fp.read(SECTOR_DATA)

path = r'C:\Users\feala\Documents\dev\translations\Yu-No - Konoyo no Hate de Koi o Utau Shoujo (Japan) (Disc A) (Track 1).bin'
with open(path, 'rb') as fp:
    pvd = read_sector(fp, 16)
    root_lba = struct.unpack('<I', pvd[156+2:156+6])[0]
    root_size = struct.unpack('<I', pvd[156+10:156+14])[0]
    print(f'Root LBA={root_lba} size={root_size}')

    block = b''
    sectors = (root_size + SECTOR_DATA - 1) // SECTOR_DATA
    for k in range(sectors):
        block += read_sector(fp, root_lba + k)
    block = block[:root_size]

    print('\nFirst 512 bytes of root dir hex:')
    for i in range(0, 512, 32):
        row = block[i:i+32]
        hexs = ' '.join(f'{b:02x}' for b in row)
        ascii_ = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
        print(f'{i:04x}  {hexs}  |{ascii_}|')

    print('\nParsed records:')
    i = 0
    n = 0
    while i < len(block) and n < 50:
        rec_len = block[i]
        if rec_len == 0:
            print(f'  off=0x{i:04x}  rec_len=0  (end-of-records padding)')
            # round up to next 2048-byte boundary
            i = ((i // SECTOR_DATA) + 1) * SECTOR_DATA
            continue
        ext_lba_le = struct.unpack('<I', block[i+2:i+6])[0]
        ext_lba_be = struct.unpack('>I', block[i+6:i+10])[0]
        size_le = struct.unpack('<I', block[i+10:i+14])[0]
        size_be = struct.unpack('>I', block[i+14:i+18])[0]
        flags = block[i+25]
        name_len = block[i+32]
        name_raw = block[i+33:i+33+name_len]
        if name_raw == b'\x00': nm = '.'
        elif name_raw == b'\x01': nm = '..'
        else: nm = name_raw.decode('ascii', errors='replace')
        print(f'  off=0x{i:04x}  rec_len={rec_len}  lba_le={ext_lba_le}  lba_be={ext_lba_be}  size_le={size_le}  size_be={size_be}  flags=0x{flags:02x}  name_len={name_len}  name={nm!r}')
        i += rec_len
        n += 1
