"""Find printable ASCII and Shift-JIS strings in a binary, with offsets."""
import sys
import re

MIN_ASCII = 4

def find_ascii(data, min_len=MIN_ASCII):
    pattern = re.compile(rb'[\x20-\x7e]{' + str(min_len).encode() + rb',}')
    for m in pattern.finditer(data):
        yield m.start(), m.group().decode('ascii', errors='replace')


def find_sjis(data, min_chars=2):
    """Find runs of valid Shift-JIS double-byte characters."""
    i = 0
    n = len(data)
    while i < n - 1:
        run_start = i
        chars = []
        while i < n - 1:
            b1 = data[i]
            b2 = data[i + 1]
            ok = ((0x81 <= b1 <= 0x9F) or (0xE0 <= b1 <= 0xFC)) and \
                 ((0x40 <= b2 <= 0x7E) or (0x80 <= b2 <= 0xFC))
            if not ok:
                break
            try:
                ch = bytes([b1, b2]).decode('shift_jis')
                chars.append(ch)
            except UnicodeDecodeError:
                break
            i += 2
        if len(chars) >= min_chars:
            yield run_start, ''.join(chars)
        else:
            i = run_start + 1


def main():
    if len(sys.argv) < 3:
        print('Usage: python find_strings.py <file> <out.txt> [--ascii|--sjis|--both]')
        sys.exit(1)
    path = sys.argv[1]
    out_path = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) >= 4 else '--both'
    with open(path, 'rb') as f:
        data = f.read()
    with open(out_path, 'w', encoding='utf-8') as out:
        out.write(f'# {path} ({len(data)} bytes)\n')
        if mode in ('--ascii', '--both'):
            out.write('## ASCII strings\n')
            for off, s in find_ascii(data):
                out.write(f'  0x{off:08x}  {s!r}\n')
        if mode in ('--sjis', '--both'):
            out.write('## Shift-JIS strings\n')
            for off, s in find_sjis(data):
                out.write(f'  0x{off:08x}  {s}\n')
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
