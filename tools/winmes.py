"""Minimal parser for YU-NO Windows (Elf Classics / AI5WIN) .MES bytecode.
Ported from nunuhara/libai5 (elf_classics opcode tables). Only what is needed to
walk statements and pull out text (ZENKAKU/HANKAKU) and string params."""
import struct, sys

STMT = {0x00:'END',0x01:'ZENKAKU',0x02:'HANKAKU',0x03:'SET_FLAG_CONST',0x04:'SET_VAR16',
 0x05:'SET_FLAG_EXPR',0x06:'PTR16_SET8',0x07:'PTR16_SET16',0x08:'PTR32_SET32',0x09:'PTR32_SET16',
 0x0A:'PTR32_SET8',0x0B:'JZ',0x0C:'JMP',0x0D:'SYS',0x0E:'JMP_MES',0x0F:'CALL_MES',0x10:'DEF_MENU',
 0x11:'CALL_PROC',0x12:'UTIL',0x13:'LINE',0x14:'DEF_PROC',0x15:'MENU_EXEC',0x16:'SET_VAR32'}

class P:
    def __init__(s,d): s.d=d; s.i=0
    def u8(s): v=s.d[s.i]; s.i+=1; return v
    def u16(s): v=struct.unpack_from('<H',s.d,s.i)[0]; s.i+=2; return v
    def u32(s): v=struct.unpack_from('<I',s.d,s.i)[0]; s.i+=4; return v
    def peek(s): return s.d[s.i]

def is_zenkaku(b): return 0x81<=b<=0x9f or 0xe0<=b<=0xef or 0xfa<=b<=0xfc

def expr(p):
    # returns list of tokens (we don't build a tree)
    while True:
        b=p.u8()
        if b==0xff: return
        if b<0x80: continue              # imm
        if 0x80<=b<=0x9f: p.u8(); continue  # GET_VAR16 (0x80 = op; libai5 reads arg8)
        if b in (0x80,0xA0,0xC0,0xF5,0xF6,0xF7,0xF8): p.u8(); continue
        if b==0xF1: p.u16(); continue
        if b==0xF2: p.u32(); continue
        if b==0xF3: p.u16(); continue
        # binary ops / F4 / E5: no immediate
        continue

def expr_list(p):
    while True:
        expr(p)
        if not p.u8(): return

def cstr(p):
    s=bytearray()
    while True:
        c=p.u8()
        if c==0: break
        s.append(c)
        if is_zenkaku(c): s.append(p.u8())
    return bytes(s)

def params(p):
    out=[]
    while True:
        b=p.u8()
        if b==0: return out
        if b==1: out.append(('str',cstr(p)))
        elif b==2: expr(p); out.append(('expr',None))
        else: raise ValueError('bad param %02x at %x'%(b,p.i))

def parse(d):
    p=P(d); stmts=[]
    while p.i<len(d):
        addr=p.i; op=p.u8(); name=STMT.get(op)
        if name is None: raise ValueError('bad op %02x at %x'%(op,addr))
        info=None
        if name=='END': pass
        elif name in ('ZENKAKU','HANKAKU'):
            s=bytearray()
            while p.peek(): s.append(p.u8())
            p.u8(); info=bytes(s)
        elif name=='SET_FLAG_CONST': p.u16(); expr_list(p)
        elif name in ('SET_VAR16','SET_VAR32'): p.u8(); expr_list(p)
        elif name=='SET_FLAG_EXPR': expr(p); expr_list(p)
        elif name.startswith('PTR'): expr(p); p.u8(); expr_list(p)
        elif name=='JZ': expr(p); info=p.u32()
        elif name=='JMP': info=p.u32()
        elif name=='SYS': expr(p); info=params(p)
        elif name in ('JMP_MES','CALL_MES','CALL_PROC','UTIL'): info=params(p)
        elif name=='DEF_MENU': info=params(p); p.u32()
        elif name=='LINE': info=p.u8()
        elif name=='DEF_PROC': expr(p); p.u32()
        elif name=='MENU_EXEC': pass
        stmts.append((addr,name,info))
    return stmts

if __name__=='__main__':
    d=open(sys.argv[1],'rb').read()
    for addr,name,info in parse(d):
        if name in ('ZENKAKU','HANKAKU'):
            print(f'{addr:05x} {name:8} {info.decode("shift_jis","replace")!r}')
        elif name in ('SYS','JMP_MES','CALL_MES','UTIL','CALL_PROC','DEF_MENU') and info:
            strs=[v.decode('shift_jis','replace') for t,v in info if t=='str']
            if strs: print(f'{addr:05x} {name:8} {strs}')
        elif name=='LINE': print(f'{addr:05x} LINE {info}')
