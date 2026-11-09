"""
YU-NO Saturn graphics ("ABG" containers inside GRAPH.ABL etc.) and Windows GP8.

ABG layout (after the 16-byte ABZ container header, all big-endian):
    0x00 u16 0x0100            0x02 u16 0x0020 (header size)
    0x04 u16 ? (0xF00F / 0xD80F)   0x06 u16 ? (0x3500)
    0x08 u16 width             0x0A u16 height
    0x0C u16 ?                 0x0E u16 ? (y offset?)
    0x10 u16 0                 0x12 u16 0
    0x14 u16 ? (1 for CGs)     0x16 u16 palette entries (255, 256, 2 ...)
    0x18 .. 0x1F zero
    0x20     palette, RGB555 (bit15 set), 2 bytes per entry
             then PackBits-style RLE of the pixel indices, stored COLUMN-MAJOR
             (index = x*height + y): byte n<0x80 = repeat next byte n times,
             byte n>=0x80 = (n&0x7f) literal bytes follow.

Windows GP8: x,y,w,h (LE16), 256x BGRX palette, LZSS pixels, rows bottom-up,
stride rounded up to 4.

Usage:
    yuno_cg.py export <GRAPH.ABL> <name> <out.png>
    yuno_cg.py gp8 <file.gp8> <out.png>
    yuno_cg.py compare <GRAPH.ABL> <win_dir_with_gp8> <out_dir> [names...]
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yuno_sat as Y


def rle_decode(d, n):
    out = bytearray()
    i = 0
    while len(out) < n and i < len(d):
        c = d[i]
        i += 1
        if c & 0x80:
            k = c & 0x7F
            out += d[i:i + k]
            i += k
        else:
            out += bytes([d[i]]) * c
            i += 1
    return bytes(out[:n])


def rle_encode(px):
    out = bytearray()
    i = 0
    n = len(px)
    lit = bytearray()

    def flush():
        nonlocal lit
        while lit:
            k = min(127, len(lit))
            out.append(0x80 | k)
            out.extend(lit[:k])
            lit = lit[k:]
    while i < n:
        j = i
        while j < n and px[j] == px[i] and j - i < 127:
            j += 1
        run = j - i
        if run >= 3 or (run >= 2 and not lit):
            flush()
            out.append(run)
            out.append(px[i])
            i = j
        else:
            lit.append(px[i])
            i += 1
    flush()
    return bytes(out)


def rgb555_to_rgb(v):
    return (round((v & 31) * 255 / 31), round(((v >> 5) & 31) * 255 / 31), round(((v >> 10) & 31) * 255 / 31))


def rgb_to_rgb555(r, g, b):
    return 0x8000 | round(r * 31 / 255) | (round(g * 31 / 255) << 5) | (round(b * 31 / 255) << 10)


def decode_abg(raw):
    """raw = decompressed ABG. Returns dict(header, w, h, palette[(r,g,b)], pixels(row-major bytes))."""
    h = struct.unpack('>16H', raw[:32])
    w, hh, npal = h[4], h[5], h[11]
    pal = [rgb555_to_rgb(v) for v in struct.unpack('>%dH' % npal, raw[32:32 + 2 * npal])]
    col = rle_decode(raw[32 + 2 * npal:], w * hh).ljust(w * hh, b'\0')
    rows = bytearray(w * hh)
    for x in range(w):
        rows[x::w] = col[x * hh:(x + 1) * hh]
    return {'header': h, 'w': w, 'h': hh, 'palette': pal, 'pixels': bytes(rows)}


def encode_abg(header, w, h, palette, pixels):
    """Inverse of decode_abg. palette: list of (r,g,b) (len = header[11]); pixels row-major indices."""
    npal = header[11]
    assert len(palette) == npal
    col = bytearray(w * h)
    for x in range(w):
        col[x * h:(x + 1) * h] = pixels[x::w]
    hdr = list(header)
    hdr[4], hdr[5] = w, h
    out = struct.pack('>16H', *hdr)
    out += struct.pack('>%dH' % npal, *(rgb_to_rgb555(*c) for c in palette))
    out += rle_encode(bytes(col)) + b'\0'
    return out


def abg_to_image(raw):
    from PIL import Image
    d = decode_abg(raw)
    img = Image.new('P', (d['w'], d['h']))
    img.putdata(d['pixels'])
    pal = []
    for c in d['palette']:
        pal += list(c)
    pal += [0, 0, 0] * (256 - len(d['palette']))
    img.putpalette(pal)
    return img.convert('RGB')


def image_to_abg(img, template_raw, max_packed=None, pack=None):
    """Convert a PIL image into an ABG with the same header/dimensions/palette size
    as the template entry (the Saturn original being replaced). BOX resampling
    averages away the PC-98 dithering of the Windows art. If max_packed is given
    (slot size in the archive) the colour count is reduced until the packed
    container fits; `pack` must then be the function raw -> packed bytes."""
    from PIL import Image
    t = decode_abg(template_raw)
    npal = t['header'][11]
    img = img.convert('RGB').resize((t['w'], t['h']), Image.BOX)
    for colors in (npal, 192, 128, 96, 64, 48, 32, 16):
        if colors > npal:
            continue
        q = img.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pal = q.getpalette()[:colors * 3]
        palette = [tuple(pal[i:i + 3]) for i in range(0, len(pal), 3)]
        palette += [(0, 0, 0)] * (npal - len(palette))
        pixels = bytes(q.tobytes())
        raw = encode_abg(t['header'], t['w'], t['h'], palette, pixels)
        if max_packed is None or len(pack(raw)) <= max_packed:
            return raw
    raise ValueError('image does not fit the archive slot even with 16 colours')


def gp8_to_image(data):
    from PIL import Image
    x, y, w, h = struct.unpack('<4H', data[:8])
    pal = data[8:8 + 1024]
    px = Y.lzss_decompress(data[8 + 1024:])
    stride = (w + 3) & ~3
    rows = bytearray()
    for i in range(h):
        rows += px[stride * (h - 1 - i):stride * (h - 1 - i) + w]
    img = Image.new('P', (w, h))
    img.putdata(rows)
    palette = []
    for i in range(256):
        b, g, r, _ = pal[i * 4:i * 4 + 4]
        palette += [r, g, b]
    img.putpalette(palette)
    img.info['offset'] = (x, y)
    return img.convert('RGB')


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'export':
        abl = Y.Abl(open(sys.argv[2], 'rb').read())
        raw, _ = Y.abz_unpack(abl.blob(sys.argv[3]))
        abg_to_image(raw).save(sys.argv[4])
        print('wrote', sys.argv[4], decode_abg(raw)['header'])
    elif cmd == 'gp8':
        gp8_to_image(open(sys.argv[2], 'rb').read()).save(sys.argv[3])
    elif cmd == 'compare':
        from PIL import Image, ImageDraw
        abl = Y.Abl(open(sys.argv[2], 'rb').read())
        win_dir, out_dir = sys.argv[3], sys.argv[4]
        os.makedirs(out_dir, exist_ok=True)
        names = sys.argv[5:] or [e['name'] for e in abl.entries if e['type'] == 1]
        wins = {f.upper(): f for f in os.listdir(win_dir)}
        n = 0
        for name in names:
            wf = wins.get(name.upper() + '.GP8')
            if not wf:
                continue
            try:
                raw, _ = Y.abz_unpack(abl.blob(name))
                a = abg_to_image(raw)
                b = gp8_to_image(open(os.path.join(win_dir, wf), 'rb').read())
            except Exception as ex:
                print('skip', name, ex)
                continue
            b = b.resize((a.width, round(b.height * a.width / b.width)))
            sheet = Image.new('RGB', (a.width * 2 + 30, max(a.height, b.height) + 24), (30, 30, 30))
            sheet.paste(a, (10, 20))
            sheet.paste(b, (a.width + 20, 20))
            ImageDraw.Draw(sheet).text((10, 4), f'{name}: Saturn {a.width}x{a.height}  |  Windows {wf}', fill=(255, 255, 255))
            sheet.save(os.path.join(out_dir, f'{name}.png'))
            n += 1
        print(f'{n} comparison sheets in {out_dir}')


if __name__ == '__main__':
    main()
