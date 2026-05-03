"""Render FONT12 with 16-byte header skipped, 24-byte glyphs."""
import sys
from PIL import Image

GRID_COLS = 32


def render(data, out_path, w, h, bpp, skip_bytes=0,
           bytes_per_glyph=None, scale=4, msb_first=True, label=''):
    if bytes_per_glyph is None:
        bytes_per_glyph = (w * h * bpp + 7) // 8
    payload = data[skip_bytes:]
    n_glyphs = len(payload) // bytes_per_glyph
    rows_n = (n_glyphs + GRID_COLS - 1) // GRID_COLS
    cell_w = (w + 2) * scale
    cell_h = (h + 2) * scale
    img = Image.new('RGB', (GRID_COLS * cell_w, rows_n * cell_h), (40, 40, 40))
    pixels = img.load()

    for idx in range(n_glyphs):
        gx = idx % GRID_COLS
        gy = idx // GRID_COLS
        ox = gx * cell_w + scale
        oy = gy * cell_h + scale
        blob = payload[idx * bytes_per_glyph:(idx + 1) * bytes_per_glyph]
        for r in range(h):
            for c in range(w):
                pix_idx = r * w + c
                byte = blob[pix_idx // 8] if pix_idx // 8 < len(blob) else 0
                bit = pix_idx & 7
                if msb_first:
                    v = (byte >> (7 - bit)) & 1
                else:
                    v = (byte >> bit) & 1
                shade = 255 if v else 0
                px = ox + c * scale
                py = oy + r * scale
                for dy in range(scale):
                    for dx in range(scale):
                        pixels[px + dx, py + dy] = (shade, shade, shade)
    img.save(out_path)
    print(f'  {label}: {n_glyphs} glyphs ({w}x{h} 1bpp, {bytes_per_glyph}B/g, skip={skip_bytes}, msb={msb_first})')


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else 'extracted/disc_a/FONT12_raw.bin'
    with open(p, 'rb') as f:
        data = f.read()
    out_dir = 'extracted/disc_a'

    # 16-byte header + 24B/glyph hypothesis
    render(data, f'{out_dir}/font_12x12_1bpp_h16.png', 12, 12, 1, 16, 24, msb_first=True, label='12x12 1bpp +pad +hdr16')
    render(data, f'{out_dir}/font_12x16_1bpp_h16.png', 12, 16, 1, 16, 24, msb_first=True, label='12x16 1bpp tight +hdr16')
    render(data, f'{out_dir}/font_16x12_1bpp_h16.png', 16, 12, 1, 16, 24, msb_first=True, label='16x12 1bpp +hdr16')
    render(data, f'{out_dir}/font_12x12_1bpp_h16_lsb.png', 12, 12, 1, 16, 24, msb_first=False, label='12x12 1bpp lsb +hdr16')


if __name__ == '__main__':
    main()
