"""
Decompress Elf 'ABZAB?' container payloads (LZSS variant from rpgwaiter/yuno-tools).

Header is 16 bytes (per segaxtreme.net thread 34635):
    0  3  ASCII 'ABZ' (or 'ABS' uncompressed)
    3  3  ASCII content type ('ABF', 'ABD', 'ABG', ...)
    6  1  compression flag (0x00 = ABS, 0x01 = ABZ)
    7  1  file code
    8  4  uncompressed size, big-endian uint32
   12  4  compressed size minus 16, big-endian uint32
   16  N  LZSS-compressed payload

LZSS:
    dict size = 0x1000, dict starts as zero, dpos starts at 0xFEE, min match = 3.
    Repeat:
      read 1 control byte; for each bit, LSB-first:
        bit=1 -> 1 literal byte (also written into dict[dpos], dpos++)
        bit=0 -> 2 bytes (data1, data2):
                   n   = (data2 & 0x0F) + 3
                   idx = ((data2 & 0xF0) << 4) | data1
                   for i in 0..n: out byte = dict[(idx+i) & 0xFFF]; dict[dpos]=byte; dpos++
"""
import struct
import sys

DICT_SIZE = 0x1000
DICT_START = 0xFEE


def decompress(payload, out_size):
    out = bytearray()
    dictbuf = bytearray(DICT_SIZE)
    dpos = DICT_START
    i = 0
    n_in = len(payload)
    while i < n_in and len(out) < out_size:
        ctrl = payload[i]; i += 1
        for bit in range(8):
            if len(out) >= out_size:
                break
            if ctrl & (1 << bit):
                if i >= n_in:
                    return bytes(out)
                b = payload[i]; i += 1
                out.append(b)
                dictbuf[dpos] = b
                dpos = (dpos + 1) & (DICT_SIZE - 1)
            else:
                if i + 1 >= n_in:
                    return bytes(out)
                d1 = payload[i]; i += 1
                d2 = payload[i]; i += 1
                length = (d2 & 0x0F) + 3
                idx = ((d2 & 0xF0) << 4) | d1
                for k in range(length):
                    if len(out) >= out_size:
                        break
                    b = dictbuf[(idx + k) & (DICT_SIZE - 1)]
                    out.append(b)
                    dictbuf[dpos] = b
                    dpos = (dpos + 1) & (DICT_SIZE - 1)
    return bytes(out)


def parse_header(data):
    magic = data[:3]
    assert magic in (b'ABZ', b'ABS'), f'Not an ABZ/ABS container: {magic!r}'
    content_type = data[3:6]
    comp_flag = data[6]
    file_code = data[7]
    uncomp_size = struct.unpack('>I', data[8:12])[0]
    comp_size_m16 = struct.unpack('>I', data[12:16])[0]
    return magic, content_type, comp_flag, file_code, uncomp_size, comp_size_m16


def main():
    if len(sys.argv) < 3:
        print('Usage: python abz_decompress.py <input.bin> <output.bin>')
        sys.exit(1)
    with open(sys.argv[1], 'rb') as f:
        data = f.read()
    magic, ctype, cflag, fcode, usize, csize_m16 = parse_header(data)
    print(f'{magic.decode()}{ctype.decode("ascii", errors="replace")}  '
          f'comp_flag=0x{cflag:02x}  file_code=0x{fcode:02x}  '
          f'uncomp_size={usize}  comp_size_minus_16={csize_m16}')
    if magic == b'ABS':
        # uncompressed
        out = data[16:16 + usize]
        with open(sys.argv[2], 'wb') as f:
            f.write(out)
        print(f'Uncompressed (ABS): wrote {len(out)} bytes')
        return
    payload = data[16:]
    print(f'Compressed payload: {len(payload)} bytes (header says {csize_m16})')
    out = decompress(payload, usize)
    print(f'Decompressed: {len(out)} bytes (expected {usize})')
    with open(sys.argv[2], 'wb') as f:
        f.write(out)
    print(f'Wrote {sys.argv[2]}')


if __name__ == '__main__':
    main()
