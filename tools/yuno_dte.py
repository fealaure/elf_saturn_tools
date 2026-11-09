"""
Dual-tile (DTE) English text for YU-NO Saturn: every 12x12 font cell holds two
6px-wide ASCII characters. Pairs are assigned to SJIS codes taken from the
kanji part of the executable's glyph code table, and the corresponding glyphs
in FONT12 are replaced with rendered character pairs.
"""
import re
import struct

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from font6x12 import GLYPHS

CELL_W = 12
LINE_CELLS = 18          # message window width in cells (36 ASCII chars), measured in-game
WINDOW_LINES = 4         # visible lines in the message window
NEWLINE = b'\x03\x00'    # control 03 (newline in documents) misbehaves in dialogue; lines are padded instead
WAIT = b'\x01\x00'       # control 01: wait for a click
FULLWIDTH_SPACE = b'\x81\x40'

# characters that exist as full-width SJIS glyphs in FONT12 and that we keep
KEEP = {'【': b'\x81\x79', '】': b'\x81\x7a'}
SUBST = {'―': '--', '…': '...', '’': "'", '‘': "'", '“': '"', '”': '"', '—': '--', '–': '-'}


class Dte:
    def __init__(self, code_table, font_raw, reserved=()):
        """code_table: list of SJIS codes (sorted) from 0.BIN; font_raw: FONT12 decompressed.
        reserved: SJIS codes whose glyphs must stay intact (e.g. kanji used by
        untranslated strings in the executable)."""
        self.codes = list(code_table)
        self.font = bytearray(font_raw)
        self.pairs = {}          # 'ab' -> sjis code (int)
        self.glyph_of = {c: i for i, c in enumerate(self.codes)}
        reserved = set(reserved)
        # pool of codes to repurpose: kanji, highest codes first
        self.pool = [c for c in self.codes if c >= 0x889f and c not in reserved]
        self.pool.sort()   # pop() takes the highest (rarest) kanji codes first

    # ---- text -> units
    @staticmethod
    def clean(s):
        for a, b in SUBST.items():
            s = s.replace(a, b)
        return s.replace('-\n', '-')      # hyphenated line breaks from the Windows script

    def wrap(self, text, width=LINE_CELLS * 2):
        """Word-wrap an ASCII string to at most `width` characters per line.
        Existing newlines are discarded and re-wrapped."""
        words = text.replace('\n', ' ').split(' ')
        lines = []
        cur = ''
        for w in words:
            if not w:
                continue
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= width:
                cur += ' ' + w
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def pair_code(self, p):
        if p == '  ':
            return 0x8140
        if p not in self.pairs:
            if not self.pool:
                raise RuntimeError('out of glyph slots for pairs')
            self.pairs[p] = self.pool.pop()
        return self.pairs[p]

    def ascii_to_units(self, s):
        if len(s) % 2:
            s += ' '
        return [struct.pack('>H', self.pair_code(s[i:i + 2])) for i in range(0, len(s), 2)]

    def message_to_units(self, en, trailing=(), stats=None):
        """en: English message (may contain a 【Name】 prefix).
        Returns a list of parts, each a list of units; a part is one text
        statement. The engine auto-wraps every LINE_CELLS cells and the window
        shows WINDOW_LINES lines, so each line except the last is padded with
        spaces to exactly LINE_CELLS cells, and a message longer than
        WINDOW_LINES lines is split into several statements separated by a
        wait-for-click control."""
        en = self.clean(en).replace('《', '<<').replace('》', '>>').replace('‥', '..')
        head = []
        m = re.match(r'^【([^】]*)】\s*', en)
        body = en
        if m:
            head.append(KEEP['【'])
            head += self.ascii_to_units(m.group(1))
            head.append(KEEP['】'])
            body = en[m.end():]
        first_w = LINE_CELLS * 2 - 2 * len(head)
        body = body.strip()
        lines = self.wrap(body, LINE_CELLS * 2)
        if lines and len(lines[0]) > first_w:
            lines = self.wrap(body, first_w)
            rest = ' '.join(lines[1:])
            lines = [lines[0]] + (self.wrap(rest, LINE_CELLS * 2) if rest else [])
        if len(lines) > WINDOW_LINES:
            # too long for one window: split the text into N balanced chunks (by
            # characters, at word boundaries) so the last part is not a lone word
            n = -(-len(lines) // WINDOW_LINES)
            words = body.split()
            total = sum(len(w_) + 1 for w_ in words)
            # break after the word closest to each balanced target, preferring
            # sentence ends (., !, ?, >>) and then clause breaks (, ; : --)
            cuts = []
            acc = 0
            pos = []
            for i, w_ in enumerate(words):
                acc += len(w_) + 1
                pos.append(acc)
            start = 0
            for c in range(1, n):
                target = total * c / n
                best = None
                for i in range(start, len(words) - 1):
                    w_ = words[i]
                    cost = abs(pos[i] - target)
                    if w_[-1] in '.!?' or w_.endswith('>>') or w_.endswith('..."'):
                        cost -= 14
                    elif w_[-1] in ',;:' or w_.endswith('--'):
                        cost -= 7
                    if best is None or cost < best[0]:
                        best = (cost, i)
                cuts.append(best[1] + 1)
                start = best[1] + 1
            chunks = []
            prev = 0
            for cpos in cuts + [len(words)]:
                chunks.append(' '.join(words[prev:cpos]))
                prev = cpos
            groups = []
            for ci, chunk in enumerate(chunks):
                fw = first_w if ci == 0 else LINE_CELLS * 2
                ls = self.wrap(chunk, LINE_CELLS * 2)
                if ls and len(ls[0]) > fw:
                    ls = self.wrap(chunk, fw)
                    rest = ' '.join(ls[1:])
                    ls = [ls[0]] + (self.wrap(rest, LINE_CELLS * 2) if rest else [])
                groups.append(ls)
            if any(len(g) > WINDOW_LINES for g in groups):   # balancing failed: plain sequential split
                groups = [lines[i:i + WINDOW_LINES] for i in range(0, len(lines), WINDOW_LINES)]
        else:
            groups = [lines]
        parts = []
        for gi, g in enumerate(groups):
            units = list(head) if gi == 0 else []
            for k, ln in enumerate(g):
                width = first_w if (gi == 0 and k == 0) else LINE_CELLS * 2
                if k < len(g) - 1:
                    ln = ln.ljust(width)           # pad so the engine wraps exactly here
                units += self.ascii_to_units(ln)
            if gi < len(groups) - 1:
                units.append(WAIT)                 # wait for a click; next statement starts a new page
                parts.append(units)
            else:
                last = units
        units = last
        lines = [ln for g in groups for ln in g]
        if stats is not None:
            stats.append((sum(1 for p in parts + [units] for u in p if u[0] >= 0x80), len(lines)))
        units += list(trailing)
        parts.append(units)
        return parts

    # ---- font
    @staticmethod
    def render_pair(p):
        a = GLYPHS.get(p[0], GLYPHS['?'])
        b = GLYPHS.get(p[1], GLYPHS['?'])
        rows = bytearray()
        for r in range(12):
            w = (a[r] << 10) | (b[r] << 4)
            rows += bytes([w >> 8, w & 0xFF])
        return bytes(rows)

    def build_font(self):
        f = bytearray(self.font)
        for p, code in self.pairs.items():
            gi = self.glyph_of[code]
            f[16 + gi * 24:16 + (gi + 1) * 24] = self.render_pair(p)
        return bytes(f)

    def preview(self, path, cols=32):
        from PIL import Image
        pairs = sorted(self.pairs)
        rows = (len(pairs) + cols - 1) // cols
        s = 3
        img = Image.new('L', (cols * 13 * s, rows * 13 * s), 60)
        px = img.load()
        for k, p in enumerate(pairs):
            blob = self.render_pair(p)
            ox, oy = (k % cols) * 13 * s, (k // cols) * 13 * s
            for r in range(12):
                w = (blob[2 * r] << 8) | blob[2 * r + 1]
                for c in range(12):
                    v = 255 if (w >> (15 - c)) & 1 else 0
                    for dy in range(s):
                        for dx in range(s):
                            px[ox + c * s + dx, oy + r * s + dy] = v
        img.save(path)
