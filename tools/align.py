"""Align Saturn script texts with the Windows JP/EN scripts and emit a
translation table (JSON) for one script name."""
import json
import os
import re
import sys
import difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yuno_sat as Y
import winmes

NAME_RE = re.compile(r'^【[^】]*】')


def win_messages(path):
    d = open(path, 'rb').read()
    st = winmes.parse(d)
    msgs = []
    cur = None
    ctx = []
    for k, (addr, name, info) in enumerate(st):
        if name in ('ZENKAKU', 'HANKAKU'):
            t = info.decode('shift_jis', 'replace')
            if cur is None:
                cur = {'addr': addr, 'text': t, 'lines': 1, 'ctx': tuple(ctx)}
                ctx = []
            else:
                cur['text'] += t
        elif name == 'LINE' and cur is not None:
            cur['text'] += '\n'
            cur['lines'] += 1
        elif name == 'CALL_PROC' and cur is not None and cur['text'].endswith('【'):
            cur['text'] += '{NAME}'
        else:
            if cur is not None:
                msgs.append(cur)
                cur = None
            key = name
            if isinstance(info, list):
                key += ':' + ','.join(v.decode('ascii', 'replace') for t, v in info if t == 'str')
            if 'VOICE_' not in key:
                ctx.append(key)
    if cur:
        msgs.append(cur)
    return msgs


def sim(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def dp_align(A, B, thr=0.6):
    """Monotonic alignment maximizing total similarity (gaps cost 0)."""
    n, m = len(A), len(B)
    import numpy as np
    S = np.zeros((n + 1, m + 1))
    bt = np.zeros((n + 1, m + 1), dtype=np.int8)
    for i in range(1, n + 1):
        ai = A[i - 1]
        for j in range(1, m + 1):
            best = S[i - 1][j]; b = 1
            if S[i][j - 1] > best:
                best = S[i][j - 1]; b = 2
            if ai:
                v = sim(ai, B[j - 1])
                if v >= thr and S[i - 1][j - 1] + v > best:
                    best = S[i - 1][j - 1] + v; b = 3
            S[i][j] = best; bt[i][j] = b
    mapping = {}
    i, j = n, m
    while i > 0 and j > 0:
        b = bt[i][j]
        if b == 3:
            mapping[i - 1] = j - 1; i -= 1; j -= 1
        elif b == 1:
            i -= 1
        else:
            j -= 1
    return mapping


def speaker(t):
    m = re.match(r'^【([^】]*)】', t)
    return m.group(1) if m else None


def align_jp_en(jp, en):
    """Align the Windows JP and EN message lists of one script. The EN script was
    recompiled by the translators, so the statement structure is only mostly
    identical; the speaker tags give a second, independent signal. A first
    structural pass learns the JP->EN name mapping, a DP pass then aligns on
    structure + speaker."""
    import collections
    sm = difflib.SequenceMatcher(None, [x['ctx'] for x in jp], [x['ctx'] for x in en], autojunk=False)
    pairs = collections.Counter()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for a, b in zip(range(i1, i2), range(j1, j2)):
                sj, se = speaker(jp[a]['text']), speaker(en[b]['text'])
                if sj and se:
                    pairs[(sj, se)] += 1
    names = {}
    for (sj, se), c in pairs.most_common():
        names.setdefault(sj, se)
    names['{NAME}'] = names.get('{NAME}', 'Takuya')
    names.setdefault('たくや', names['{NAME}'])

    def score(a, b):
        sj, se = speaker(jp[a]['text']), speaker(en[b]['text'])
        s = 0.0
        if jp[a]['ctx'] == en[b]['ctx']:
            s += 1.0
        if sj and se:
            s += 1.0 if names.get(sj) == se else -2.0
        elif not sj and not se:
            s += 0.5
        else:
            s -= 1.0
        return s

    n, m = len(jp), len(en)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best, b = S[i - 1][j], 1
            if S[i][j - 1] > best:
                best, b = S[i][j - 1], 2
            v = score(i - 1, j - 1)
            if v > 0 and S[i - 1][j - 1] + v > best:
                best, b = S[i - 1][j - 1] + v, 3
            S[i][j], bt[i][j] = best, b
    out = {}
    i, j = n, m
    while i > 0 and j > 0:
        b = bt[i][j]
        if b == 3:
            out[i - 1] = j - 1
            i -= 1
            j -= 1
        elif b == 1:
            i -= 1
        else:
            j -= 1
    return out, names


def fix_speaker(jp_text, en_text, names):
    """Make the EN speaker tag agree with the Saturn JP line (the global
    dictionary may return the same sentence said by another character)."""
    sj = speaker(jp_text)
    if not sj or sj not in names:
        return en_text
    want = names[sj]
    m = re.match(r'^【([^】]*)】\s*', en_text)
    if m and m.group(1) != want:
        return f'【{want}】 ' + en_text[m.end():]
    if not m:
        return f'【{want}】 ' + en_text
    return en_text


def norm_jp(s):
    s = re.sub(r'\{NAME\}', '', s)
    s = NAME_RE.sub('', s)
    return re.sub(r'[\s\n]', '', s)


def main(abl_path, name, win_jp, win_en, out_json):
    abl = Y.Abl(open(abl_path, 'rb').read())
    raw, hdr = Y.abz_unpack(abl.blob(name))
    mes = Y.SatMes(raw)
    sat = []
    for k, (s, e, units) in enumerate(mes.texts()):
        txt = Y.SatMes.units_to_text(units)
        sat.append({'idx': k, 'text': txt, 'norm': norm_jp(re.sub(r'<[^>]*>', '', txt))})
    jp = win_messages(win_jp)
    en = win_messages(win_en)
    print(f'saturn texts {len(sat)}, win jp msgs {len(jp)}, win en msgs {len(en)}')
    jp2en, names = align_jp_en(jp, en)
    print(f'jp->en matches: {len(jp2en)}/{len(jp)}; speakers: {names}')
    # align sat (non-empty) to jp by normalized text
    sat_keys = [x['norm'] for x in sat]
    jp_keys = [norm_jp(x['text']) for x in jp]
    mapping = dp_align(sat_keys, jp_keys)
    matched = len(mapping)
    unmatched = [x for x in sat if x['idx'] not in mapping and x['norm']]
    print(f'matched {matched}; unmatched non-empty saturn texts: {len(unmatched)}')
    for x in unmatched[:20]:
        print('   SAT', x['idx'], x['text'])
    G = json.load(open('/mnt/user-data/uploads/elf_saturn_tools/extracted/win_dict.json'))
    gkeys = list(G.keys())
    table = []
    nfb = 0
    for x in sat:
        entry = {'idx': x['idx'], 'jp': x['text']}
        if x['idx'] not in mapping and x['norm']:
            k = x['norm']
            hit = G.get(k)
            if hit is None:
                cands = [g for g in gkeys if abs(len(g) - len(k)) <= 3]
                m = difflib.get_close_matches(k, cands, 1, 0.8)
                if m:
                    hit = G[m[0]]
            if hit:
                entry['win_jp'] = hit['jp']
                entry['en'] = fix_speaker(x['text'], hit['en'], names)
                entry['src'] = hit['file']
                nfb += 1
        if x['idx'] in mapping:
            j = mapping[x['idx']]
            entry['win_jp'] = jp[j]['text']
            if j in jp2en:
                entry['en'] = fix_speaker(x['text'], en[jp2en[j]]['text'], names)
        table.append(entry)
    print('global-dict fallbacks:', nfb)
    # sanity: speaker tags must agree, otherwise text and voice drift apart in-game
    bad = 0
    for e in table:
        if 'en' in e:
            sj, se = speaker(e['jp']), speaker(e['en'])
            if (sj is None) != (se is None) or (sj and se and names.get(sj) and names[sj] != se):
                bad += 1
                print('   SPEAKER MISMATCH', e['idx'], e['jp'][:30], '|', e['en'][:40].replace('\n', ' '))
    print('speaker mismatches:', bad)
    json.dump(table, open(out_json, 'w'), ensure_ascii=False, indent=1)
    print('wrote', out_json)


if __name__ == '__main__':
    main(*sys.argv[1:])
