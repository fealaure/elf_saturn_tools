"""
Extract files from a Saturn MODE1/2352 .bin image (ISO 9660 filesystem).
Strips the 16-byte sync/header from each sector and walks the directory tree.

Usage:
    python extract_saturn_iso.py <input.bin> <output_dir>
"""
import os
import sys
import struct

SECTOR_RAW = 2352      # MODE1/2352
SECTOR_DATA = 2048     # user data per sector
SECTOR_HEADER = 16     # 12 sync + 3 addr + 1 mode


def read_sector(fp, lba):
    """Return 2048 bytes of user data for the given Logical Block Address."""
    fp.seek(lba * SECTOR_RAW + SECTOR_HEADER)
    data = fp.read(SECTOR_DATA)
    if len(data) != SECTOR_DATA:
        raise IOError(f"Short read at LBA {lba}")
    return data


def read_extent(fp, lba, size):
    """Read `size` bytes starting at sector `lba`, hopping per-sector overhead."""
    out = bytearray()
    while size > 0:
        chunk = read_sector(fp, lba)
        take = min(SECTOR_DATA, size)
        out += chunk[:take]
        size -= take
        lba += 1
    return bytes(out)


def parse_dir_records(block):
    """Yield (name, lba, size, is_dir) tuples from a directory extent block."""
    i = 0
    while i < len(block):
        rec_len = block[i]
        if rec_len == 0:
            # End of records in this sector; advance to next 2048-byte boundary
            next_boundary = ((i // SECTOR_DATA) + 1) * SECTOR_DATA
            if next_boundary >= len(block):
                return
            i = next_boundary
            continue

        ext_lba = struct.unpack('<I', block[i + 2:i + 6])[0]
        ext_size = struct.unpack('<I', block[i + 10:i + 14])[0]
        flags = block[i + 25]
        name_len = block[i + 32]
        name_raw = block[i + 33:i + 33 + name_len]

        is_dir = bool(flags & 0x02)

        if name_raw == b'\x00':
            name = '.'
        elif name_raw == b'\x01':
            name = '..'
        else:
            name = name_raw.decode('ascii', errors='replace')
            # Strip ISO 9660 version suffix `;1`
            if ';' in name:
                name = name.split(';', 1)[0]

        yield (name, ext_lba, ext_size, is_dir)
        i += rec_len


def walk_and_extract(fp, lba, size, out_dir, indent=0, listing=None, total_sectors=None):
    """Recursively extract a directory."""
    block = read_extent(fp, lba, size)
    os.makedirs(out_dir, exist_ok=True)
    for name, child_lba, child_size, is_dir in parse_dir_records(block):
        if name in ('.', '..'):
            continue
        path = os.path.join(out_dir, name)
        rel = os.path.relpath(path, ROOT_OUT)
        # Skip references that point past the end of this track (e.g. CDDA placeholder)
        end_sector = child_lba + (child_size + SECTOR_DATA - 1) // SECTOR_DATA
        if total_sectors is not None and end_sector > total_sectors:
            line = '  ' * indent + f'[SKIP] {name}  (LBA {child_lba} past end of track)'
            print(line)
            if listing is not None:
                listing.append(f'{rel}\tSKIPPED_PAST_EOT\t{child_lba}')
            continue
        if is_dir:
            line = '  ' * indent + f'[DIR] {name}/'
            print(line)
            if listing is not None:
                listing.append(f'{rel}/')
            walk_and_extract(fp, child_lba, child_size, path, indent + 1, listing, total_sectors)
        else:
            data = read_extent(fp, child_lba, child_size)
            with open(path, 'wb') as out:
                out.write(data)
            line = '  ' * indent + f'{name}  ({child_size} bytes, LBA {child_lba})'
            print(line)
            if listing is not None:
                listing.append(f'{rel}\t{child_size}\t{child_lba}')


def main():
    global ROOT_OUT
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    in_bin, out_dir = sys.argv[1], sys.argv[2]
    ROOT_OUT = out_dir

    bin_size = os.path.getsize(in_bin)
    total_sectors = bin_size // SECTOR_RAW
    print(f'Track 1 size: {bin_size} bytes -> {total_sectors} sectors')

    with open(in_bin, 'rb') as fp:
        # Primary Volume Descriptor lives at LBA 16
        pvd = read_sector(fp, 16)
        if pvd[1:6] != b'CD001':
            print(f"PVD signature not found; got {pvd[1:6]!r}")
            sys.exit(2)

        # Root directory record lives at offset 156 of the PVD (34 bytes long)
        root_record = pvd[156:156 + 34]
        root_lba = struct.unpack('<I', root_record[2:6])[0]
        root_size = struct.unpack('<I', root_record[10:14])[0]
        vol_id = pvd[40:72].decode('ascii', errors='replace').strip()
        print(f"Volume: {vol_id}")
        print(f"Root LBA={root_lba}  size={root_size}")
        print('---')

        listing = []
        walk_and_extract(fp, root_lba, root_size, out_dir, listing=listing, total_sectors=total_sectors)

        # Save flat listing for later reference
        listing_path = os.path.join(out_dir, '_listing.txt')
        with open(listing_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(listing))
        print('---')
        print(f'Listing written to {listing_path}')


if __name__ == '__main__':
    main()
