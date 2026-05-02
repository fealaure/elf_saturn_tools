"""
Patch a Saturn MODE1/2352 .bin disc image at byte ranges inside files of its
ISO 9660 filesystem, then recompute EDC + ECC (Reed-Solomon) for affected
sectors so the resulting disc is bit-correct under strict emulators.

Sector layout (MODE1/2352):
    0x0000..0x000B  sync (12 bytes)
    0x000C..0x000E  address (MSF, 3 bytes)
    0x000F          mode = 0x01
    0x0010..0x080F  user data (2048 bytes)
    0x0810..0x0813  EDC (CRC32 with poly 0xD8018001, over bytes 0..0x0813 input)
    0x0814..0x081B  intermediate zeros (8 bytes)
    0x081C..0x08C7  ECC P (172 bytes)
    0x08C8..0x092F  ECC Q (104 bytes)
"""
import os
import shutil
import struct
import sys

SECTOR_RAW = 2352
SECTOR_DATA = 2048
SECTOR_HEADER = 16

# --- EDC / ECC tables ---
ecc_f_lut = [0] * 256
ecc_b_lut = [0] * 256
edc_lut = [0] * 256


def eccedc_init():
    for i in range(256):
        j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
        ecc_f_lut[i] = j
        ecc_b_lut[i ^ j] = i
        edc = i
        for _ in range(8):
            edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
        edc_lut[i] = edc


def edc_compute(data, edc=0):
    for b in data:
        edc = (edc >> 8) ^ edc_lut[(edc ^ b) & 0xFF]
    return edc & 0xFFFFFFFF


def ecc_compute_block(src, major_count, minor_count, major_mult, minor_inc, dest):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _ in range(minor_count):
            temp = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_a ^= temp
            ecc_b ^= temp
            if ecc_a:
                ecc_a = ecc_f_lut[ecc_a]
        ecc_a = ecc_b_lut[ecc_f_lut[ecc_a] ^ ecc_b]
        dest[major] = ecc_a
        dest[major + major_count] = (ecc_a ^ ecc_b) & 0xFF


def recompute_sector(sector):
    """Take a 2352-byte MODE1 sector (bytearray) and rewrite EDC + zeros + ECC."""
    assert len(sector) == SECTOR_RAW
    # EDC over bytes 0..0x813 (=2068)? Actually input is 0..0x0810 = 2064 bytes
    edc = edc_compute(bytes(sector[0:2064]))
    sector[2064:2068] = struct.pack('<I', edc)
    sector[2068:2076] = b'\x00' * 8
    # ECC P: input bytes 0x0C..0x081C  (12..2076) = 2064 bytes; output at 0x081C..0x08C8
    p_dest = bytearray(172)
    ecc_compute_block(bytes(sector[12:2076]), 86, 24, 2, 86, p_dest)
    sector[2076:2248] = p_dest
    # ECC Q: input bytes 0x0C..0x08C8  (12..2248) = 2236 bytes; output at 0x08C8..0x0930
    q_dest = bytearray(104)
    ecc_compute_block(bytes(sector[12:2248]), 52, 43, 86, 88, q_dest)
    sector[2248:2352] = q_dest


def file_offset_to_raw(file_offset, file_lba):
    """Map an offset inside a file (whose first sector is file_lba in the disc)
    to a raw .bin byte offset, accounting for the 16-byte sector header."""
    sector_idx = file_offset // SECTOR_DATA
    in_sector = file_offset % SECTOR_DATA
    disc_lba = file_lba + sector_idx
    return disc_lba * SECTOR_RAW + SECTOR_HEADER + in_sector


def patch_file_inside_bin(bin_path, file_lba, file_offset, new_bytes):
    """Overwrite `new_bytes` at `file_offset` inside the file starting at LBA
    `file_lba`. Recomputes EDC+ECC for every sector it touches."""
    raw_start = file_offset_to_raw(file_offset, file_lba)
    raw_end = raw_start + len(new_bytes)

    # Identify all sectors touched
    first_disc_lba = file_lba + (file_offset // SECTOR_DATA)
    last_file_offset = file_offset + len(new_bytes) - 1
    last_disc_lba = file_lba + (last_file_offset // SECTOR_DATA)

    print(f'  raw bytes {raw_start}..{raw_end - 1}  '
          f'disc LBA {first_disc_lba}..{last_disc_lba}')

    with open(bin_path, 'r+b') as f:
        # Write the patched bytes (handling cross-sector spans)
        cursor = file_offset
        remaining = bytes(new_bytes)
        while remaining:
            sector_idx = cursor // SECTOR_DATA
            in_sector = cursor % SECTOR_DATA
            disc_lba = file_lba + sector_idx
            space_in_sector = SECTOR_DATA - in_sector
            chunk = remaining[:space_in_sector]
            f.seek(disc_lba * SECTOR_RAW + SECTOR_HEADER + in_sector)
            f.write(chunk)
            cursor += len(chunk)
            remaining = remaining[len(chunk):]

        # Recompute EDC/ECC for every touched sector
        for disc_lba in range(first_disc_lba, last_disc_lba + 1):
            f.seek(disc_lba * SECTOR_RAW)
            sector = bytearray(f.read(SECTOR_RAW))
            recompute_sector(sector)
            f.seek(disc_lba * SECTOR_RAW)
            f.write(sector)
            print(f'  recomputed EDC/ECC for LBA {disc_lba}')


def self_test(bin_path, test_lba=24):
    """Read an unmodified sector, recompute EDC/ECC, verify match."""
    print(f'Self-test: reading unmodified LBA {test_lba} from {bin_path}')
    with open(bin_path, 'rb') as f:
        f.seek(test_lba * SECTOR_RAW)
        original = f.read(SECTOR_RAW)
    rebuilt = bytearray(original)
    recompute_sector(rebuilt)
    if bytes(rebuilt) == original:
        print('  OK: EDC + ECC match the original sector. Implementation is correct.')
        return True
    # Show first divergence
    for i, (a, b) in enumerate(zip(original, rebuilt)):
        if a != b:
            print(f'  MISMATCH at byte {i:#06x}: original={a:02x}  computed={b:02x}')
            print(f'  Original window: {original[max(0,i-4):i+8].hex()}')
            print(f'  Computed window: {bytes(rebuilt[max(0,i-4):i+8]).hex()}')
            break
    return False


def main():
    eccedc_init()

    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        # python patch_disc.py selftest <bin> [lba]
        bin_path = sys.argv[2]
        lba = int(sys.argv[3]) if len(sys.argv) >= 4 else 24
        sys.exit(0 if self_test(bin_path, lba) else 1)

    if len(sys.argv) < 6 or len(sys.argv) % 2 != 0:
        print('Usage:')
        print('  python patch_disc.py selftest <input.bin> [lba]')
        print('  python patch_disc.py <input.bin> <output.bin> <file_lba> '
              '<file_offset_hex> <hex_bytes> [<file_offset_hex> <hex_bytes>...]')
        sys.exit(1)

    in_bin, out_bin, file_lba_s = sys.argv[1], sys.argv[2], sys.argv[3]
    file_lba = int(file_lba_s)
    patches = []
    for i in range(4, len(sys.argv), 2):
        off = int(sys.argv[i], 16)
        new_bytes = bytes.fromhex(sys.argv[i + 1])
        patches.append((off, new_bytes))

    print(f'Copying {in_bin} -> {out_bin}')
    shutil.copyfile(in_bin, out_bin)
    print(f'Done ({os.path.getsize(out_bin)} bytes)')

    if not self_test(out_bin):
        print('Self-test FAILED — aborting before applying patches.')
        sys.exit(2)

    for off, new_bytes in patches:
        print(f'Patching @ file offset {off:#x}: {new_bytes!r}')
        patch_file_inside_bin(out_bin, file_lba, off, new_bytes)

    print('All patches applied.')


if __name__ == '__main__':
    main()
