"""
Minimal ISO 9660 / Saturn MODE1-2352 disc image helpers for patching files
in place or relocating a (grown) file to the end of the data track.
Reuses the EDC/ECC code from patch_disc.py.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_disc as PD

SECTOR_RAW = 2352
SECTOR_DATA = 2048
SECTOR_HEADER = 16
PD.eccedc_init()


def lba_to_msf_bytes(lba):
    """Sector header address field (BCD MSF) for a given LBA (adds the 150-sector offset)."""
    f = lba + 150
    m, rem = divmod(f, 75 * 60)
    s, fr = divmod(rem, 75)
    bcd = lambda v: ((v // 10) << 4) | (v % 10)
    return bytes([bcd(m), bcd(s), bcd(fr)])


def msf_str(sectors):
    m, rem = divmod(sectors, 75 * 60)
    s, fr = divmod(rem, 75)
    return f'{m:02d}:{s:02d}:{fr:02d}'


def make_sector(lba, data):
    """Build a complete MODE1/2352 sector for `data` (<= 2048 bytes)."""
    assert len(data) <= SECTOR_DATA
    sec = bytearray(SECTOR_RAW)
    sec[0:12] = b'\x00' + b'\xff' * 10 + b'\x00'
    sec[12:15] = lba_to_msf_bytes(lba)
    sec[15] = 1
    sec[16:16 + len(data)] = data
    PD.recompute_sector(sec)
    return bytes(sec)


class Disc:
    def __init__(self, bin_path):
        self.path = bin_path
        self.size = os.path.getsize(bin_path)
        self.f = open(bin_path, 'rb')
        self.total_sectors = self.size // SECTOR_RAW
        pvd = self.read_data(16)
        assert pvd[1:6] == b'CD001', 'no PVD'
        self.volume_space = struct.unpack('<I', pvd[80:84])[0]
        root = pvd[156:156 + 34]
        self.root_lba = struct.unpack('<I', root[2:6])[0]
        self.root_size = struct.unpack('<I', root[10:14])[0]
        self.files = self._read_dir(self.root_lba, self.root_size)

    def read_data(self, lba):
        self.f.seek(lba * SECTOR_RAW + SECTOR_HEADER)
        return self.f.read(SECTOR_DATA)

    def read_raw(self, lba):
        self.f.seek(lba * SECTOR_RAW)
        return self.f.read(SECTOR_RAW)

    def read_file(self, name):
        e = self.files[name]
        out = bytearray()
        lba, size = e['lba'], e['size']
        while size > 0:
            d = self.read_data(lba)
            out += d[:min(SECTOR_DATA, size)]
            size -= SECTOR_DATA
            lba += 1
        return bytes(out)

    def _read_dir(self, lba, size):
        block = bytearray()
        for k in range((size + SECTOR_DATA - 1) // SECTOR_DATA):
            block += self.read_data(lba + k)
        files = {}
        i = 0
        while i < size:
            rl = block[i]
            if rl == 0:
                i = ((i // SECTOR_DATA) + 1) * SECTOR_DATA
                continue
            name_len = block[i + 32]
            name = bytes(block[i + 33:i + 33 + name_len])
            if name not in (b'\x00', b'\x01'):
                nm = name.decode('ascii').split(';')[0]
                files[nm] = {
                    'rec_sector': lba + i // SECTOR_DATA,
                    'rec_off': i % SECTOR_DATA,
                    'lba': struct.unpack('<I', block[i + 2:i + 6])[0],
                    'size': struct.unpack('<I', block[i + 10:i + 14])[0],
                }
            i += rl
        return files


def patch_record(data, off, lba=None, size=None):
    """Rewrite LBA/size (both-endian) of a directory record inside a 2048-byte block."""
    data = bytearray(data)
    if lba is not None:
        data[off + 2:off + 6] = struct.pack('<I', lba)
        data[off + 6:off + 10] = struct.pack('>I', lba)
    if size is not None:
        data[off + 10:off + 14] = struct.pack('<I', size)
        data[off + 14:off + 18] = struct.pack('>I', size)
    return bytes(data)


def build_disc(src_bin, src_cue, dst_bin, dst_cue, inplace_files, relocate_files, data_track_end, log=print):
    """
    inplace_files : {name: bytes}  -- same LBA, must fit the original extent
    relocate_files: {name: bytes}  -- appended at the end of the data track
    data_track_end: LBA of the first sector after the last file (start of postgap)
    """
    disc = Disc(src_bin)
    for lba in (16, 24, 1000, data_track_end - 1):
        assert make_sector(lba, disc.read_data(lba)) == disc.read_raw(lba), f'sector builder self-test failed at LBA {lba}'
    log('  sector builder self-test OK (sync/MSF/EDC/ECC match the original image)')
    # ---- plan sector modifications
    modified = {}   # lba -> 2048 data
    for name, data in inplace_files.items():
        e = disc.files[name]
        ext = (e['size'] + SECTOR_DATA - 1) // SECTOR_DATA
        need = (len(data) + SECTOR_DATA - 1) // SECTOR_DATA
        assert need <= ext, f'{name}: {len(data)} bytes does not fit extent of {ext} sectors'
        for k in range(need):
            chunk = data[k * SECTOR_DATA:(k + 1) * SECTOR_DATA]
            old = disc.read_data(e['lba'] + k)
            chunk = chunk + b'\0' * (SECTOR_DATA - len(chunk))
            if chunk != old:
                modified[e['lba'] + k] = chunk
        if len(data) != e['size']:
            rec = modified.get(e['rec_sector'], disc.read_data(e['rec_sector']))
            modified[e['rec_sector']] = patch_record(rec, e['rec_off'], size=len(data))
        log(f'  {name}: in place at LBA {e["lba"]}, {len(data)} bytes, {sum(1 for l in modified if e["lba"] <= l < e["lba"] + need)} sectors changed')

    appended = []   # list of (lba, data) for new sectors
    next_lba = data_track_end
    for name, data in relocate_files.items():
        e = disc.files[name]
        n = (len(data) + SECTOR_DATA - 1) // SECTOR_DATA
        for k in range(n):
            chunk = data[k * SECTOR_DATA:(k + 1) * SECTOR_DATA]
            appended.append((next_lba + k, chunk + b'\0' * (SECTOR_DATA - len(chunk))))
        rec = modified.get(e['rec_sector'], disc.read_data(e['rec_sector']))
        modified[e['rec_sector']] = patch_record(rec, e['rec_off'], lba=next_lba, size=len(data))
        log(f'  {name}: relocated to LBA {next_lba} ({n} sectors, {len(data)} bytes); old extent at LBA {e["lba"]} left unused')
        next_lba += n
    grow = next_lba - data_track_end

    if grow:
        # shift the CDDA placeholder record and the volume size
        if 'CDDA.PCM' in disc.files:
            e = disc.files['CDDA.PCM']
            rec = modified.get(e['rec_sector'], disc.read_data(e['rec_sector']))
            modified[e['rec_sector']] = patch_record(rec, e['rec_off'], lba=e['lba'] + grow)
        pvd = bytearray(modified.get(16, disc.read_data(16)))
        vs = struct.unpack('<I', pvd[80:84])[0] + grow
        pvd[80:84] = struct.pack('<I', vs)
        pvd[84:88] = struct.pack('>I', vs)
        modified[16] = bytes(pvd)

    # ---- locate postgap / audio in the source image
    with open(src_cue, encoding='utf-8', errors='replace') as f:
        cue = f.read()
    import re
    m = re.search(r'TRACK 02 AUDIO.*?INDEX 01 (\d+):(\d+):(\d+)', cue, re.S)
    mm, ss, ff = map(int, m.groups())
    track2_start = (mm * 60 + ss) * 75 + ff
    postgap = track2_start - data_track_end
    log(f'  data track: {data_track_end} sectors + {postgap} postgap; audio from sector {track2_start}; growing by {grow} sectors')
    assert 0 <= postgap <= 300

    # ---- write
    def copy_range(out, first, last):
        """Copy sectors [first, last) from the source image in large blocks."""
        disc.f.seek(first * SECTOR_RAW)
        remaining = (last - first) * SECTOR_RAW
        while remaining > 0:
            buf = disc.f.read(min(remaining, 8 << 20))
            if not buf:
                raise IOError('unexpected end of source image')
            out.write(buf)
            remaining -= len(buf)

    with open(dst_bin, 'wb') as out:
        pos = 0
        for lba in sorted(modified):
            if lba >= data_track_end:
                continue
            copy_range(out, pos, lba)
            out.write(make_sector(lba, modified[lba]))
            pos = lba + 1
        copy_range(out, pos, data_track_end)
        for lba, data in appended:
            out.write(make_sector(lba, data))
        for k in range(postgap):
            out.write(make_sector(data_track_end + grow + k, b'\0' * SECTOR_DATA))
        disc.f.seek(track2_start * SECTOR_RAW)
        while True:
            buf = disc.f.read(1 << 20)
            if not buf:
                break
            out.write(buf)
    new_cue = re.sub(r'(TRACK 02 AUDIO.*?INDEX 01 )\d+:\d+:\d+', lambda m_: m_.group(1) + msf_str(track2_start + grow), cue, flags=re.S)
    new_cue = re.sub(r'FILE "[^"]*"', f'FILE "{os.path.basename(dst_bin)}"', new_cue)
    with open(dst_cue, 'w', encoding='utf-8') as f:
        f.write(new_cue)
    log(f'  wrote {dst_bin} ({os.path.getsize(dst_bin)} bytes) and {dst_cue}')
