"""Build a global JP->EN message dictionary from the Windows MES scripts.
usage: win_dict.py <win_jp_dir> <win_en_dir> <out.json>"""
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winmes

NAME_RE = re.compile(r'^【[^】]*】')


def win_messages(path):
    d = open(path, 'rb').read()
    try:
        st = winmes.parse(d)
    except Exception as ex:
        print('parse error', path, ex)
        return []
    msgs = []
    cur = None
    ctx = []
    for k, (addr, name, info) in enumerate(st):
        if name in ('ZENKAKU', 'HANKAKU'):
            t = info.decode('shift_jis', 'replace')
            if cur is None:
                cur = {'addr': addr, 'text': t, 'ctx': tuple(ctx)}
                ctx = []
            else:
                cur['text'] += t
        elif name == 'LINE' and cur is not None:
            cur['text'] += '\n'
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


def norm_jp(s):
    s = re.sub(r'\{NAME\}', '', s)
    s = NAME_RE.sub('', s)
    return re.sub(r'[\s\n]', '', s)


def main(jp_dir, en_dir, out):
    D = {}
    files = sorted(f for f in os.listdir(jp_dir) if f.upper().endswith('.MES'))
    tot = 0
    for f in files:
        pe = os.path.join(en_dir, f)
        if not os.path.exists(pe):
            continue
        jp = win_messages(os.path.join(jp_dir, f))
        en = win_messages(pe)
        sm = difflib.SequenceMatcher(None, [x['ctx'] for x in jp], [x['ctx'] for x in en], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                for a, b in zip(range(i1, i2), range(j1, j2)):
                    k = norm_jp(jp[a]['text'])
                    if k and k not in D:
                        D[k] = {'en': en[b]['text'], 'file': f, 'jp': jp[a]['text']}
                        tot += 1
    json.dump(D, open(out, 'w'), ensure_ascii=False)
    print(f'{len(files)} files, {tot} entries -> {out}')


if __name__ == '__main__':
    main(*sys.argv[1:])
