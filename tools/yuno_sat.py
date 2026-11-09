"""
YU-NO (Sega Saturn) script tools: ABLINK archive access, ABZ (LZSS) compression,
and the Saturn .MES text encoding (per-file character table + fragment dictionary).

Saturn MES layout (all big-endian):
    0x00 u16  0x44nn : nn = number of entries in the character table T
    0x02 u16  label_off   : code ends here; label table starts (u16 code-relative offsets, +0x10 = file offset)
    0x04 u16  frag_off    : fragment pointer table (u16 offsets relative to tab_off)
    0x06 u16  tab_off     : character table T (2-byte units: SJIS char or control 01 00 / 02 00 / 03 00)
    0x08 u16  end         : file length
    0x0A      zeros
    0x10      bytecode

Text statement: 0x91 <codes...> 0x00
    code c in 1..nT             -> T[c-1]
    code c in nT+1..0xFA        -> F[c-nT-1]           (K = 0xFA-nT one-byte fragment codes)
    code 0xFB..0xFD, n (0..249) -> F[K-1 + (c-0xFB)*250 + n]   (n may be 0)
Fragments are byte strings of units, null-terminated in the pool.
"""
import struct
import sys

# ---------------------------------------------------------------- LZSS (ABZ) ---
DICT_SIZE = 0x1000
DICT_START = 0xFEE
MIN_MATCH = 3
MAX_MATCH = 18


def lzss_decompress(payload, out_size=None):
    out = bytearray()
    dictbuf = bytearray(DICT_SIZE)
    dpos = DICT_START
    i = 0
    n = len(payload)
    while i < n and (out_size is None or len(out) < out_size):
        ctrl = payload[i]
        i += 1
        for bit in range(8):
            if out_size is not None and len(out) >= out_size:
                break
            if ctrl & (1 << bit):
                if i >= n:
                    return bytes(out)
                b = payload[i]
                i += 1
                out.append(b)
                dictbuf[dpos] = b
                dpos = (dpos + 1) & (DICT_SIZE - 1)
            else:
                if i + 1 >= n:
                    return bytes(out)
                d1 = payload[i]
                d2 = payload[i + 1]
                i += 2
                length = (d2 & 0x0F) + 3
                idx = ((d2 & 0xF0) << 4) | d1
                for k in range(length):
                    b = dictbuf[(idx + k) & (DICT_SIZE - 1)]
                    out.append(b)
                    dictbuf[dpos] = b
                    dpos = (dpos + 1) & (DICT_SIZE - 1)
    return bytes(out)


def lzss_compress(data):
    """LZSS compressor compatible with lzss_decompress, using optimal parsing
    (dynamic programming over literal/match choices). The decoder dictionary
    is a 4096-byte ring initialised to zero with the write position starting
    at 0xFEE, so a match at output position p refers to ring index
    (0xFEE + p) & 0xFFF; matches may overlap the bytes being written."""
    data = bytes(data)
    n = len(data)
    if n == 0:
        return b''
    # longest match for every position (hash chains on 3-byte prefixes)
    from collections import defaultdict
    chains = defaultdict(list)
    best_len = [0] * n
    best_pos = [0] * n
    for i in range(n):
        if i + MIN_MATCH <= n:
            key = data[i:i + 3]
            cands = chains.get(key)
            if cands:
                bl = 0
                bp = 0
                lim = min(MAX_MATCH, n - i)
                for p in reversed(cands):
                    if i - p > DICT_SIZE - MAX_MATCH:   # too far back: would be overwritten
                        break
                    l = 3
                    while l < lim and data[p + l] == data[i + l]:
                        l += 1
                    if l > bl:
                        bl = l
                        bp = p
                        if l == lim:
                            break
                best_len[i] = bl
                best_pos[i] = bp
            chains[key].append(i)
    # optimal parse: cost in bits (literal 9, match 17)
    INF = float('inf')
    cost = [INF] * (n + 1)
    choice = [0] * (n + 1)      # 0 = literal, else match length
    cost[n] = 0
    for i in range(n - 1, -1, -1):
        c = 9 + cost[i + 1]
        ch = 0
        bl = best_len[i]
        if bl >= MIN_MATCH:
            # any length between MIN_MATCH and bl is available at the same position
            for l in range(MIN_MATCH, bl + 1):
                cc = 17 + cost[i + l]
                if cc < c:
                    c = cc
                    ch = l
        cost[i] = c
        choice[i] = ch
    # emit
    out = bytearray()
    ctrl_pos = 0
    ctrl = 0
    nbits = 0
    out.append(0)
    i = 0
    while i < n:
        l = choice[i]
        if l:
            ring = (DICT_START + best_pos[i]) & (DICT_SIZE - 1)
            out.append(ring & 0xFF)
            out.append(((ring >> 4) & 0xF0) | (l - 3))
            i += l
        else:
            ctrl |= 1 << nbits
            out.append(data[i])
            i += 1
        nbits += 1
        if nbits == 8:
            out[ctrl_pos] = ctrl
            ctrl = 0
            nbits = 0
            if i < n:
                ctrl_pos = len(out)
                out.append(0)
    if nbits:
        out[ctrl_pos] = ctrl
    return bytes(out)


def abz_unpack(blob):
    magic = blob[:3]
    ctype = blob[3:6]
    usize = struct.unpack('>I', blob[8:12])[0]
    csize = struct.unpack('>I', blob[12:16])[0]
    if magic == b'ABS':
        return blob[16:16 + usize], blob[:16]
    assert magic == b'ABZ', magic
    return lzss_decompress(blob[16:16 + csize], usize), blob[:16]


def abz_pack(raw, header16):
    """Rebuild an ABZ container keeping the original header's type/flags."""
    comp = lzss_compress(raw)
    h = bytearray(header16)
    h[8:12] = struct.pack('>I', len(raw))
    h[12:16] = struct.pack('>I', len(comp))
    return bytes(h) + comp


# ---------------------------------------------------------------- ABLINK ---
class Abl:
    def __init__(self, data):
        self.data = bytearray(data)
        assert self.data[:6] == b'ABLINK'
        self.count = struct.unpack('>I', self.data[12:16])[0]
        self.entries = []
        for i in range(self.count):
            r = self.data[16 + i * 12:28 + i * 12]
            name = r[:8].rstrip(b'\0').decode('ascii')
            sector = (r[9] << 16) | (r[10] << 8) | r[11]
            self.entries.append({'i': i, 'name': name, 'type': r[8], 'sector': sector})
        order = sorted(self.entries, key=lambda e: e['sector'])
        for k, e in enumerate(order):
            nxt = order[k + 1]['sector'] * 2048 if k + 1 < len(order) else len(self.data)
            e['slot'] = nxt - e['sector'] * 2048

    def find(self, name):
        for e in self.entries:
            if e['name'] == name:
                return e
        raise KeyError(name)

    def blob(self, name):
        e = self.find(name)
        off = e['sector'] * 2048
        csize = struct.unpack('>I', self.data[off + 12:off + 16])[0]
        return bytes(self.data[off:off + 16 + csize])

    def replace(self, name, blob):
        """Replace an entry's data. If it fits the current slot it is written in
        place; otherwise the whole archive is re-laid out so that index order
        stays equal to storage order (the game derives an entry's length from
        the next index entry, so entries can never be appended out of order).
        Returns 'inplace' or 'relayout'."""
        e = self.find(name)
        if len(blob) <= e['slot']:
            off = e['sector'] * 2048
            self.data[off:off + e['slot']] = blob + b'\0' * (e['slot'] - len(blob))
            how = 'inplace'
        else:
            blobs = {x['name']: self.blob(x['name']) for x in self.entries}
            blobs[name] = blob
            self._relayout(blobs)
            how = 'relayout'
        self._update_total()
        return how

    def _relayout(self, blobs):
        hdr_sectors = (16 + 12 * self.count + 2047) // 2048
        out = bytearray(self.data[:16 + 12 * self.count]) + b'\0' * (hdr_sectors * 2048 - 16 - 12 * self.count)
        for e in self.entries:            # index order == storage order
            b = blobs[e['name']]
            sector = len(out) // 2048
            n = (len(b) + 2047) // 2048
            out += b + b'\0' * (n * 2048 - len(b))
            i = e['i']
            out[16 + i * 12 + 9:16 + i * 12 + 12] = bytes([(sector >> 16) & 0xFF, (sector >> 8) & 0xFF, sector & 0xFF])
            e['sector'] = sector
            e['slot'] = n * 2048
        self.data = out

    def _update_total(self):
        # header[8..12] = sum of (csize+16) over entries, as in the original
        total = 0
        for x in self.entries:
            o = x['sector'] * 2048
            total += struct.unpack('>I', self.data[o + 12:o + 16])[0] + 16
        self.data[8:12] = struct.pack('>I', total)


# ---------------------------------------------------------------- MES text ---
CTL = {0x01: '<wait>', 0x02: '<pause>', 0x03: '<ctl3>', 0x05: '<ctl5>'}


class SatMes:
    def __init__(self, raw):
        self.raw = bytes(raw)
        h = struct.unpack('>8H', raw[:16])
        self.unk0 = h[0]
        self.label_off, self.frag_off, self.tab_off, self.end = h[1], h[2], h[3], h[4]
        self.code = self.raw[16:self.label_off]
        self.code_pad = 0
        if len(self.code) and self.code[-1] == 0 and self.code[-2:-1] != b'\x91':
            self.code_pad = 1   # alignment pad byte added by the original compiler
        self.labels = list(struct.unpack('>%dH' % ((self.frag_off - self.label_off) // 2),
                                         raw[self.label_off:self.frag_off]))
        fptr = struct.unpack('>%dH' % ((self.tab_off - self.frag_off) // 2), raw[self.frag_off:self.tab_off])
        t_end = self.tab_off + (fptr[0] if fptr else self.end - self.tab_off)
        self.T = [bytes(raw[i:i + 2]) for i in range(self.tab_off, t_end, 2)]
        assert (self.unk0 & 0xFF) == len(self.T), f'header says {self.unk0 & 0xFF} table entries, found {len(self.T)}'
        self.F = []
        for v in fptr:
            p = self.tab_off + v
            e = raw.index(b'\0', p)
            self.F.append(bytes(raw[p:e]))

    # -- decoding
    @staticmethod
    def units(b):
        """Split a fragment byte string into 2-byte units. Controls 01 (wait) and
        02 (pause) carry one parameter byte (e.g. 02 78 = pause 120 frames); a
        missing parameter (end of fragment) means 0. Control 03 (newline) has none."""
        out = []
        i = 0
        while i < len(b):
            c = b[i]
            if c >= 0x80:
                out.append(b[i:i + 2])
                i += 2
            elif c != 0x03 and i + 1 < len(b):
                out.append(b[i:i + 2])        # control + parameter byte (01 p, 02 p, 05 p, ...)
                i += 2
            else:
                out.append(b[i:i + 1] + b'\0')  # 03 (newline) has no parameter
                i += 1
        return out

    def decode_codes(self, codes):
        nT = len(self.T)
        K = 0xFA - nT
        units = []
        i = 0
        while i < len(codes):
            c = codes[i]
            i += 1
            if c == 0:
                break
            if c <= nT:
                units.append(self.T[c - 1])
            elif c <= 0xFA:
                units.extend(self.units(self.F[c - nT - 1]))
            else:
                n = codes[i]
                i += 1
                units.extend(self.units(self.F[K - 1 + (c - 0xFB) * 250 + n]))
        return units

    @staticmethod
    def units_to_text(units):
        s = ''
        for u in units:
            if u[0] >= 0x80:
                s += u.decode('shift_jis', 'replace')
            elif u[0] in CTL and u[1]:
                s += CTL[u[0]][:-1] + ' %d>' % u[1]
            else:
                s += CTL.get(u[0], '<%02x%02x>' % (u[0], u[1]))
        return s

    @staticmethod
    def text_end(code, i):
        """Offset of the terminating 0x00 of the text statement at code[i] (0x91),
        honouring the two-byte fragment codes FB..FD whose parameter may be 0x00."""
        j = i + 1
        while j < len(code):
            c = code[j]
            if c == 0:
                return j
            j += 2 if c >= 0xFB else 1
        return -1

    def texts(self):
        """Yield (code_offset, end_offset, units) for each 0x91 text statement."""
        code = self.code
        i = 0
        res = []
        while i < len(code):
            if code[i] == 0x91:
                e = self.text_end(code, i)
                if e < 0:
                    break
                try:
                    units = self.decode_codes(code[i + 1:e])
                except IndexError:
                    units = None
                if units and all(self.unit_ok(u) for u in units):
                    res.append((i, e + 1, units))
                    i = e + 1
                    continue
            i += 1
        return res

    STRPARAM_RE = None

    def string_params(self):
        """Menu labels and other Shift-JIS string parameters embedded in the code
        as `ee <string> 00`. Returns (start, end, text) with code[start:end] = the
        string bytes (terminator excluded). Only strings with at least one
        double-byte character are returned (file names are plain ASCII)."""
        import re
        if SatMes.STRPARAM_RE is None:
            SatMes.STRPARAM_RE = re.compile(rb'\xee((?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]|[\x20-\x7e])+)\x00')
        out = []
        for m in SatMes.STRPARAM_RE.finditer(self.code):
            b = m.group(1)
            if not any(x >= 0x80 for x in b):
                continue
            try:
                t = b.decode('shift_jis')
            except UnicodeDecodeError:
                continue
            out.append((m.start(1), m.end(1), t))
        return out

    @staticmethod
    def unit_ok(u):
        if u[0] >= 0x80:
            try:
                u.decode('shift_jis')
                return True
            except UnicodeDecodeError:
                return False
        return u[0] in CTL and (u[1] == 0 or u[0] != 0x03)


def choose_tables(new_texts, ngrams=True, tmax=0xEF, min_gain=1):
    """Pick the character table T and fragment list F for a set of unit lists.
    Returns (T, F, encode) where encode(units) -> code bytes."""
    from collections import Counter
    unit_cnt = Counter()
    for units in new_texts:
        unit_cnt.update(units)
    distinct = [u for u, _ in unit_cnt.most_common()]
    assert len(distinct) <= tmax + 3 * 250, f'too many distinct units: {len(distinct)}'

    # candidate n-grams (2..8 units), estimated with 2-byte codes
    cands = []
    if ngrams:
        gram = Counter()
        for units in new_texts:
            for L in range(2, 9):
                for i in range(len(units) - L + 1):
                    gram[tuple(units[i:i + L])] += 1
        for g, c in gram.items():
            L = len(g)
            gain = c * (L - 2) - (2 * L + 3)
            if gain >= min_gain:
                cands.append((gain, g))
        cands.sort(reverse=True)

    frags = [g for _, g in cands]
    for _ in range(4):
        # T = most common units overall (singles not in T must live in F)
        T = distinct[:tmax]
        tset = set(T)
        nT = len(T)
        K = 0xFA - nT
        FMAX = K - 1 + 3 * 250
        singles = [(u,) for u in distinct[tmax:]]
        F = singles + [g for g in frags if g not in singles]
        F = F[:FMAX]
        # trial encode to measure usage
        enc = _make_encoder(T, F, K)
        use = Counter()
        for units in new_texts:
            for fi in enc(units, trace=True):
                use[fi] += 1
        # drop n-grams that are not worth it, order F by usage (1-byte codes first)
        keep = []
        for i, g in enumerate(F):
            if len(g) == 1 or use[i] * (len(g) - 2) - (2 * len(g) + 3) >= min_gain:
                keep.append((use[i], i, g))
        keep.sort(key=lambda x: -x[0])
        newF = [g for _, _, g in keep][:FMAX]
        if newF == F:
            break
        frags = [g for g in newF if len(g) > 1]
    F = newF
    enc = _make_encoder(T, F, K)
    return T, F, enc


def _make_encoder(T, F, K):
    nT = len(T)
    tidx = {u: i + 1 for i, u in enumerate(T)}
    fidx = {g: i for i, g in enumerate(F)}
    maxL = max((len(g) for g in F), default=0)

    def fcode(i):
        if i < K:
            return bytes([nT + 1 + i])
        page, n = divmod(i - (K - 1), 250)     # parameter byte may be 0 (seen in the originals)
        return bytes([0xFB + page, n])

    def encode(units, trace=False):
        out = bytearray()
        used = []
        i = 0
        while i < len(units):
            best = None
            for L in range(min(maxL, len(units) - i), 0, -1):
                g = tuple(units[i:i + L])
                if g in fidx:
                    # prefer the table for single units that are in T
                    if L == 1 and g[0] in tidx:
                        break
                    best = (L, fidx[g])
                    break
            if best:
                out += fcode(best[1])
                used.append(best[1])
                i += best[0]
            else:
                out.append(tidx[units[i]])
                i += 1
        return used if trace else bytes(out)
    return encode


def build_mes(mes, new_texts, ngrams=True, min_gain=80, tmax=0xEF, verbatim=(), return_spans=False, edits=()):
    """Rebuild a SatMes with its text statements replaced.
    new_texts: list of unit lists (same length/order as mes.texts()).
    Returns bytes of the new file."""
    old = mes.texts()
    assert len(old) == len(new_texts)
    verbatim = set(verbatim)   # indices of "texts" copied byte-for-byte (suspected false positives of the scanner)
    # a text may be split into several consecutive statements: item = [part, part, ...]
    parts_of = [t if (t and isinstance(t[0], list)) else [t] for t in new_texts]
    flat = [p for k, ps in enumerate(parts_of) if k not in verbatim for p in ps]
    T, F, encode = choose_tables(flat, ngrams, tmax=tmax, min_gain=min_gain)

    def encode_parts(ps):
        return b''.join(b'\x91' + encode(p) + b'\0' for p in ps)
    # --- rebuild code with relocated labels
    # all replacements (texts and string-parameter edits) sorted by position
    items = []
    for k, (s, e, _) in enumerate(old):
        items.append((s, e, 'text', k))
    for (s, e, nb) in edits:
        items.append((s, e, 'edit', nb))
    items.sort(key=lambda x: x[0])
    for a_, b_ in zip(items, items[1:]):
        assert a_[1] <= b_[0], f'overlapping edits at {a_[0]:#x}/{b_[0]:#x}'
    code = bytearray()
    pos = 0
    spans = [None] * len(old)
    deltas = []   # (old_end_offset, cumulative delta) used to relocate labels
    cum = 0
    for (s, e, kind, payload) in items:
        code += mes.code[pos:s]
        start = len(code)
        if kind == 'text':
            k = payload
            if k in verbatim:
                code += mes.code[s:e]
            else:
                code += encode_parts(parts_of[k])
            spans[k] = (start, len(code))
        else:
            code += payload
        pos = e
        cum += (len(code) - start) - (e - s)
        deltas.append((e, cum))
    code += mes.code[pos:len(mes.code) - mes.code_pad]
    # the label/fragment/char tables are u16 arrays read by the SH-2: they must
    # start at an even offset, so the original compiler pads the code with one
    # 0x00 byte when needed. An odd label_off crashes the game (address error).
    if (16 + len(code)) % 2:
        code.append(0)

    def relocate(o):
        d = 0
        for e, cum in deltas:
            if o >= e:
                d = cum
            else:
                break
        return o + d

    labels = [relocate(l) for l in mes.labels]
    # --- tables
    tab = bytearray()
    for u in T:
        tab += u
    fptr = []
    for g in F:
        fptr.append(len(tab))
        for u in g:
            if u[0] >= 0x80 or u[0] != 0x03:
                tab += u                      # char, or control + its parameter byte (01 00, 02 78, ...)
            else:
                tab += u[:1]                  # 03 (newline) has no parameter
        tab += b'\0'
    label_off = 16 + len(code)
    frag_off = label_off + 2 * len(labels)
    tab_off = frag_off + 2 * len(fptr)
    end = tab_off + len(tab)
    # header word 0 = 0x44xx where xx = number of entries in the character table T
    word0 = (mes.unk0 & 0xFF00) | len(T)
    hdr = struct.pack('>8H', word0, label_off, frag_off, tab_off, end, 0, 0, 0)
    out = hdr + bytes(code) + struct.pack('>%dH' % len(labels), *labels) + \
        struct.pack('>%dH' % len(fptr), *fptr) + bytes(tab)
    if return_spans:
        return out, spans
    return out


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('usage: yuno_sat.py <SENARIO.ABL> <name> [dump|hex]')
        sys.exit(1)
    abl = Abl(open(sys.argv[1], 'rb').read())
    name = sys.argv[2]
    raw, hdr = abz_unpack(abl.blob(name))
    mes = SatMes(raw)
    print(f'# {name}: raw {len(raw)} bytes, T={len(mes.T)} F={len(mes.F)} labels={len(mes.labels)} slot={abl.find(name)["slot"]}')
    for k, (s, e, units) in enumerate(mes.texts()):
        print(f'{k:4d} @{16 + s:05x} {SatMes.units_to_text(units)}')
