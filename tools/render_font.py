"""
Render FONT12_raw.bin (decompressed) to PNG grids in several candidate
pixel formats so we can spot which one looks like real glyphs.
"""
import sys
from PIL import Image

GRID_COLS = 32  # glyphs per row in output


def render(data, out_path, w, h, bpp, layout='linear', skip_bytes=0,
           bytes_per_glyph=None, scale=3, label=''):
    """layout: 'linear' (rows top-to-bottom, MSB-first nibbles)
              'linear_lo' (LSB-first nibbles)
              'planar' (1bpp planes interleaved)"""
    if bytes_per_glyph is None:
        bytes_per_glyph = (w * h * bpp + 7) // 8
    payload = data[skip_bytes:]
    n_glyphs = len(payload) // bytes_per_glyph
    rows_n = (n_glyphs + GRID_COLS - 1) // GRID_COLS
    cell_w = (w + 2) * scale
    cell_h = (h + 2) * scale
    img = Image.new('RGB', (GRID_COLS * cell_w, rows_n * cell_h), (40, 40, 40))
    pixels = img.load()
    max_val = (1 << bpp) - 1
    shade_mult = 255 // max_val if max_val > 0 else 255

    for idx in range(n_glyphs):
        gx = idx % GRID_COLS
        gy = idx // GRID_COLS
        ox = gx * cell_w + scale
        oy = gy * cell_h + scale
        blob = payload[idx * bytes_per_glyph:(idx + 1) * bytes_per_glyph]
        for r in range(h):
            for c in range(w):
                if bpp == 4:
                    pix_idx = r * w + c
                    byte = blob[pix_idx // 2] if pix_idx // 2 < len(blob) else 0
                    if layout == 'linear_lo':
                        v = (byte >> 4) if (pix_idx & 1) else (byte & 0xF)
                    else:
                        v = (byte & 0xF) if (pix_idx & 1) else (byte >> 4)
                elif bpp == 1:
                    pix_idx = r * w + c
                    byte = blob[pix_idx // 8] if pix_idx // 8 < len(blob) else 0
                    bit = pix_idx & 7
                    if layout == 'linear_lo':
                        v = (byte >> bit) & 1
                    else:
                        v = (byte >> (7 - bit)) & 1
                elif bpp == 2:
                    pix_idx = r * w + c
                    byte = blob[pix_idx // 4] if pix_idx // 4 < len(blob) else 0
                    pos = pix_idx & 3
                    if layout == 'linear_lo':
                        v = (byte >> (pos * 2)) & 3
                    else:
                        v = (byte >> ((3 - pos) * 2)) & 3
                else:
                    v = 0
                shade = v * shade_mult
                px = ox + c * scale
                py = oy + r * scale
                for dy in range(scale):
                    for dx in range(scale):
                        pixels[px + dx, py + dy] = (shade, shade, shade)
    img.save(out_path)
    print(f'  {label or out_path}: {n_glyphs} glyphs ({w}x{h} {bpp}bpp, {bytes_per_glyph}B/g, skip={skip_bytes}, {layout})')


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else 'extracted/disc_a/FONT12_raw.bin'
    with open(p, 'rb') as f:
        data = f.read()

    out_dir = 'extracted/disc_a'

    # Candidate formats
    render(data, f'{out_dir}/font_12x12_4bpp_msb.png', 12, 12, 4, 'linear', 0, 72, label='12x12 4bpp MSB')
    render(data, f'{out_dir}/font_12x12_4bpp_lsb.png', 12, 12, 4, 'linear_lo', 0, 72, label='12x12 4bpp LSB')
    render(data, f'{out_dir}/font_12x12_1bpp_msb.png', 12, 12, 1, 'linear', 0, 18, label='12x12 1bpp MSB')
    render(data, f'{out_dir}/font_24x24_1bpp_msb.png', 24, 24, 1, 'linear', 0, 72, label='24x24 1bpp MSB')
    render(data, f'{out_dir}/font_16x16_4bpp_msb.png', 16, 16, 4, 'linear', 0, 128, label='16x16 4bpp MSB')
    render(data, f'{out_dir}/font_12x24_2bpp_msb.png', 12, 24, 2, 'linear', 0, 72, label='12x24 2bpp MSB')


if __name__ == '__main__':
    main()
