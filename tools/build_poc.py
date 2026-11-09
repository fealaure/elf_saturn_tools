"""
Build the YU-NO Saturn English proof-of-concept disc image.

    python tools/build_poc.py [--src <disc1.bin>] [--out build/]

Inputs:
    translations/scripts/<NAME>.json   per-script text tables (from align.py)
    translations/menus.json            system menu strings in 0.BIN
Outputs (in --out):
    Yuno Disc 1 (ENG PoC).bin / .cue, SENARIO.ABL, OTHER.ABL, 0.BIN, pairs.png, build.log
"""
import argparse
import glob
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import yuno_sat as Y
import yuno_dte as D
import iso_tools as I

GLYPH_TABLE_MAGIC = b'\x81\x40\x81\x41\x81\x42\x81\x43'
MAX_RAW = 20558        # largest decompressed script in SENARIO.ABL (Z64_02)
MAX_PACKED = 16384     # largest slot (8 sectors) in SENARIO.ABL


def is_sjis_pair(b, p):
    return p >= 0 and (0x81 <= b[p] <= 0x9f or 0xe0 <= b[p] <= 0xef) and 0x40 <= b[p + 1] <= 0xfc and b[p + 1] != 0x7f


def find_glyph_table(exe):
    p = exe.index(GLYPH_TABLE_MAGIC)
    # walk forward while codes increase
    i = p
    prev = -1
    while True:
        v = struct.unpack('>H', exe[i:i + 2])[0]
        if v <= prev or v > 0xEAA4:
            break
        prev = v
        i += 2
    return p, list(struct.unpack('>%dH' % ((i - p) // 2), exe[p:i]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=os.path.join(ROOT, 'Yuno Disc 1 of 2 (J)(Saturn)', 'Yuno Disc 1 of 2 (J).bin'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'build'))
    ap.add_argument('--no-iso', action='store_true', help='only rebuild the files, skip the disc image')
    ap.add_argument('--debug', choices=['none', 'jp-roundtrip', 'no-scripts', 'relocate-only'], default='none',
                    help='bisect helper: jp-roundtrip = rebuild scripts with the original Japanese text; no-scripts = leave SENARIO.ABL untouched; relocate-only = untouched SENARIO.ABL moved to the end of the data track')
    ap.add_argument('--allow-big', action='store_true', help='allow scripts larger than any original one')
    ap.add_argument('--files', help='read 0.BIN/SENARIO.ABL/OTHER.ABL from this directory instead of the disc image (implies --no-iso)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    logf = open(os.path.join(a.out, 'build.log'), 'w', encoding='utf-8')

    def log(*x):
        s = ' '.join(str(v) for v in x)
        print(s)
        logf.write(s + '\n')

    if a.files:
        a.no_iso = True
        read_file = lambda n: open(os.path.join(a.files, n), 'rb').read()
    else:
        disc = I.Disc(a.src)
        read_file = disc.read_file
    exe = bytearray(read_file('0.BIN'))
    senario = Y.Abl(read_file('SENARIO.ABL'))
    other = Y.Abl(read_file('OTHER.ABL'))
    toff, codes = find_glyph_table(exe)
    log(f'glyph code table at 0.BIN+0x{toff:x}: {len(codes)} codes')
    font_raw, font_hdr = Y.abz_unpack(other.blob('FONT12'))
    log(f'FONT12: {len(font_raw)} bytes raw, {(len(font_raw) - 16) // 24} glyphs')
    # kanji used by strings inside the executable must keep their glyphs, so that
    # system text we do not translate still renders
    reserved = set()
    for m_ in re.finditer(rb'(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]){2,}\x00', bytes(exe)):
        b = m_.group()[:-1]
        try:
            b.decode('shift_jis')
        except UnicodeDecodeError:
            continue
        reserved.update(struct.unpack('>%dH' % (len(b) // 2), b))
    dte = D.Dte(codes, font_raw, reserved=reserved)
    log(f'DTE pool: {len(dte.pool)} kanji glyph slots available ({len(reserved)} codes reserved for 0.BIN strings)')
    labels = json.load(open(os.path.join(ROOT, 'translations', 'labels.json'), encoding='utf-8'))

    # ---- scripts
    for path in sorted(glob.glob(os.path.join(ROOT, 'translations', 'scripts', '*.json'))):
        name = os.path.splitext(os.path.basename(path))[0]
        table = json.load(open(path, encoding='utf-8'))
        raw, hdr = Y.abz_unpack(senario.blob(name))
        mes = Y.SatMes(raw)
        old = mes.texts()
        assert len(old) == len(table), f'{name}: table has {len(table)} entries, script has {len(old)} texts'
        if a.debug in ('no-scripts', 'relocate-only'):
            log(f'{name}: skipped (--debug no-scripts)')
            continue
        new = []
        n_en = 0
        verbatim = []
        for k, ((s, e, units), entry) in enumerate(zip(old, table)):
            en = entry.get('en_edit') or entry.get('en')
            if en and a.debug != 'jp-roundtrip':
                trailing = [u for u in units if u[0] < 0x80 and u[0] in (1, 2)]
                new.append(dte.message_to_units(en, trailing[-1:] if trailing else []))
                n_en += 1
            else:
                new.append(units)
                # a Japanese text with no Windows counterpart may be a false positive of
                # the 0x91 scanner (bytes inside another statement): leave it untouched
                if not entry.get('win_jp') and any(u[0] >= 0x80 for u in units):
                    verbatim.append(k)
                    log(f'  {name}: text #{k} kept verbatim (no Windows match): {entry["jp"][:40]}')
        # menu labels / string parameters embedded in the code
        edits = []
        n_lab = 0
        for (s, e, jp) in mes.string_params():
            en = labels.get(jp)
            if en is None:
                log(f'  {name}: label without translation: {jp}')
                continue
            edits.append((s, e, b''.join(dte.ascii_to_units(dte.clean(en)))))
            n_lab += 1
        out, spans = Y.build_mes(mes, new, verbatim=verbatim, return_spans=True, edits=edits)
        chk = Y.SatMes(out)
        for k, (s2, e2) in enumerate(spans):
            if k in verbatim:
                assert chk.code[s2:e2] == mes.code[old[k][0]:old[k][1]]
                continue
            parts = new[k] if (new[k] and isinstance(new[k][0], list)) else [new[k]]
            p = s2
            for part in parts:
                assert chk.code[p] == 0x91
                q = Y.SatMes.text_end(chk.code, p)
                assert chk.decode_codes(chk.code[p + 1:q]) == part, f'{name}: text #{k} does not decode back'
                p = q + 1
            assert p == e2
        assert len(chk.labels) == len(mes.labels)
        n_split = sum(1 for t in new if t and isinstance(t[0], list) and len(t) > 1)
        log(f'  {name}: {n_lab} menu labels translated, {n_split} long messages split')
        blob = Y.abz_pack(out, hdr)
        assert Y.lzss_decompress(blob[16:], len(out)) == out
        # stay within the largest sizes found in the original archive (buffer sizes in 0.BIN are unknown)
        if len(out) > MAX_RAW or len(blob) > MAX_PACKED:
            msg = f'{name}: rebuilt script is {len(out)} bytes raw / {len(blob)} packed; original maxima are {MAX_RAW} / {MAX_PACKED}'
            if a.allow_big:
                log('WARNING ' + msg)
            else:
                raise SystemExit(msg + ' (use --allow-big to override)')
        how = senario.replace(name, blob)
        log(f'{name}: {n_en}/{len(old)} texts translated; raw {len(raw)} -> {len(out)}; packed {len(blob)} ({how}, slot {senario.find(name)["slot"]})')

    # ---- system menu strings in 0.BIN
    menus = json.load(open(os.path.join(ROOT, 'translations', 'menus.json'), encoding='utf-8'))
    for item in menus:
        jp = item['jp'].encode('shift_jis')
        en = dte.clean(item['en'])
        enc = b''.join(dte.ascii_to_units(en))
        if 'at' in item:
            p = int(item['at'], 16)
            assert exe[p:p + len(jp)] == jp, f'menu string not at {item["at"]}: {item["jp"]}'
            hits = [p]
        else:
            hits = [m.start() for m in re.finditer(re.escape(jp) + b'\x00', bytes(exe))
                    if not (is_sjis_pair(exe, m.start() - 2) and is_sjis_pair(exe, m.start() - 4))]
            assert hits, f'menu string not found: {item["jp"]}'
        for p in hits:
            assert len(enc) <= len(jp), f'"{item["en"]}" ({len(enc)} bytes) longer than "{item["jp"]}" ({len(jp)} bytes)'
            exe[p:p + len(jp) + 1] = enc + b'\0' * (len(jp) + 1 - len(enc))
        log(f'menu: "{item["jp"]}" -> "{en}" at {[hex(h) for h in hits]}')

    # ---- replacement CGs (translations/cg/NAME.png or NAME.gp8 -> GRAPH.ABL entry NAME)
    cg_files = sorted(glob.glob(os.path.join(ROOT, 'translations', 'cg', '*')))
    graph = None
    if cg_files:
        import yuno_cg as C
        from PIL import Image
        graph = Y.Abl(read_file('GRAPH.ABL'))
        for path in cg_files:
            name, ext = os.path.splitext(os.path.basename(path))
            name = name.upper()
            try:
                tmpl_blob = graph.blob(name)
            except KeyError:
                log(f'cg: no GRAPH.ABL entry named {name}, skipped')
                continue
            tmpl_raw, tmpl_hdr = Y.abz_unpack(tmpl_blob)
            if ext.lower() == '.gp8':
                img = C.gp8_to_image(open(path, 'rb').read())
            else:
                img = Image.open(path)
            slot = graph.find(name)['slot']
            new_raw = C.image_to_abg(img, tmpl_raw, max_packed=slot if not a.allow_big else None,
                                     pack=lambda r: Y.abz_pack(r, tmpl_hdr))
            blob = Y.abz_pack(new_raw, tmpl_hdr)
            how = graph.replace(name, blob)
            log(f'cg: {name} <- {os.path.basename(path)}: {len(blob)} bytes ({how}, slot {graph.find(name)["slot"]})')

    # ---- font
    log(f'DTE pairs used: {len(dte.pairs)}')
    new_font = dte.build_font()
    fblob = Y.abz_pack(new_font, font_hdr)
    assert Y.lzss_decompress(fblob[16:], len(new_font)) == new_font
    how = other.replace('FONT12', fblob)
    log(f'FONT12 packed {len(fblob)} bytes ({how}, slot {other.find("FONT12")["slot"]})')
    assert how == 'inplace', 'FONT12 must stay in place (OTHER.ABL cannot grow in this build)'
    try:
        dte.preview(os.path.join(a.out, 'pairs.png'))
    except Exception as ex:  # PIL missing
        log('preview skipped:', ex)
    json.dump({p: '%04x' % c for p, c in sorted(dte.pairs.items())}, open(os.path.join(a.out, 'pairs.json'), 'w'), indent=0)

    # ---- write rebuilt files
    for nm, data in [('SENARIO.ABL', bytes(senario.data)), ('OTHER.ABL', bytes(other.data)), ('0.BIN', bytes(exe))] + \
            ([('GRAPH.ABL', bytes(graph.data))] if graph is not None else []):
        with open(os.path.join(a.out, nm), 'wb') as f:
            f.write(data)
    if a.no_iso:
        return
    # ---- disc image
    data_end = max(e['lba'] + (e['size'] + 2047) // 2048 for n, e in disc.files.items() if n != 'CDDA.PCM')
    inplace = {'0.BIN': bytes(exe), 'OTHER.ABL': bytes(other.data)}
    reloc = {}
    if len(senario.data) <= disc.files['SENARIO.ABL']['size'] and a.debug != 'relocate-only':
        inplace['SENARIO.ABL'] = bytes(senario.data)
    else:
        reloc['SENARIO.ABL'] = bytes(senario.data)
    if graph is not None:
        if len(graph.data) <= disc.files['GRAPH.ABL']['size']:
            inplace['GRAPH.ABL'] = bytes(graph.data)
        else:
            reloc['GRAPH.ABL'] = bytes(graph.data)
    dst = os.path.join(a.out, 'Yuno Disc 1 (ENG PoC).bin')
    src_cue = os.path.splitext(a.src)[0] + '.cue'
    log('building disc image...')
    I.build_disc(a.src, src_cue, dst, os.path.splitext(dst)[0] + '.cue', inplace, reloc, data_end, log=log)
    log('done')


if __name__ == '__main__':
    main()
