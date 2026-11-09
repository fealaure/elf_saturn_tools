# YU-NO (Sega Saturn) — formatos e pipeline de tradução

Resultado da engenharia reversa feita em 2026-11-08. Tudo em big-endian salvo indicação.

## Disco (Disc 1)
- Track 1 MODE1/2352, 216273 setores de dados + 150 de postgap; track 2 = CDDA.
- Arquivos no root: `0.BIN` (executável SH-2), `SENARIO.ABL` (881 scripts), `OTHER.ABL`
  (fonte `FONT12`, cursor, moldura…), `GRAPH.ABL` (inclui `FONTANK`, `LOGO`), `KAKOMI.ABL`,
  `MUSIC.ABL`, `EFFECT.ABL`, `VOICE.ABL`, `MOVIE.ABL`.
- A faixa de dados está 100% cheia: para crescer um arquivo, `iso_tools.build_disc` o realoca
  para o fim da faixa, insere setores (cabeçalho MSF + EDC/ECC regenerados), corrige o registro
  no diretório raiz, o PVD (volume size), o `CDDA.PCM` e o `INDEX 01` da faixa 2 no `.cue`.

## ABLINK (`*.ABL`)
- Header 16 bytes: `ABLINK`, versão `02 01`, u32 = soma de (tamanho comprimido + 16) de todas
  as entradas (informativo), u32 = nº de entradas.
- Entradas de 12 bytes: nome (8, ASCII), tipo (1), offset em setores de 2048 (u24).
- Cada entrada ocupa um "slot" até a próxima (alinhado a 2048). `Abl.replace()` grava no lugar
  se couber, senão anexa no fim do arquivo e repõe o offset no índice.

## Contêiner ABZ / ABS
- `ABZ`+tipo(3) + flag + código + u32 tamanho descomprimido + u32 tamanho comprimido + payload.
- LZSS idêntico ao da versão Windows (dicionário 0x1000, início 0xFEE, match 3..18, bit 1 = literal).
  `yuno_sat.lzss_compress` produz ~0,3% a mais que o compressor original.

## Script `.MES` do Saturn (diferente do bytecode AI5WIN do PC)
```
0x00 u16 ?           0x02 u16 label_off   0x04 u16 frag_off
0x06 u16 tab_off     0x08 u16 end         0x10.. bytecode
```
- Word 0 do header = `0x44nn`, nn = número de entradas de `T` (o jogo usa esse valor).
- `label_off`, `frag_off` e `tab_off` são sempre pares (tabelas u16 lidas pelo SH-2); quando o
  código tem tamanho ímpar o compilador acrescenta um byte `00`. Offset ímpar = address error
  (tela branca). O último statement de todo script é `83`.
- `label_off`: tabela de rótulos (u16, offset relativo a 0x10). Saltos usam índice de rótulo
  (`28 LL <expr> 87` = JZ), não endereços absolutos — por isso basta realocar a tabela ao
  mudar o tamanho dos textos.
- Statement de texto: `91 <códigos> 00`. Códigos: `1..nT` → unidade `T[c-1]`;
  `nT+1..0xFA` → fragmento `F[c-nT-1]`; `FB/FC/FD nn` (nn=0..249, **nn pode ser 00**) →
  `F[K-1+(c-0xFB)*250+nn]`, com `K = 0xFA - nT`. Ao procurar o `00` final é preciso pular o
  parâmetro desses códigos.
- `T` (em `tab_off`): unidades de 2 bytes — char Shift-JIS ou controle. Controles: `01 p`
  (espera clique), `02 p` (pausa; p = duração em frames, ex. `02 78`), `03` (quebra de linha,
  sem parâmetro; só funciona na janela de documentos), `05 p` (desconhecido). Dentro de
  fragmentos os controles sempre levam o byte de parâmetro (`01 00`, `02 78`, `05 3c`); o motor
  expande o fragmento byte a byte até encontrar um `00` fora de parâmetro. Um fragmento `02`
  seguido só do terminador faz o motor "vazar" para o fragmento seguinte (apareceu como um
  "ky" solto no fim de falas com pausa).
- `F`: ponteiros u16 relativos a `tab_off` para sequências de unidades terminadas em `00`.
- Buffer do script no executável: 32 KB (`heap+0x4A030`, logo antes da fonte em `heap+0x52030`).
  O loader (`0x0603FDC0`) calcula o tamanho de uma entrada do ABL como
  `(offset da entrada seguinte no índice − offset desta) × 2048`.
- Outros statements vistos: `88 ee "NOME" 00` (JMP_MES), `a0 ee "H01_2" 00` (fundo),
  `ac ee "YUNO_15" 00` (BGM), `c0 ee "B00267" 00` (voz), `c1 <expr> 87` (SE), `84 xx xx`.
- Janela de diálogo: 18 células de 12 px por linha, 4 linhas visíveis (medido no emulador);
  a janela de documentos tem 25. Quebras de linha em diálogo são feitas preenchendo a linha com
  espaços até 18 células (o motor quebra sozinho na 18ª célula).

## Fonte
- `FONT12` (OTHER.ABL): 16 bytes de header + 2137 glifos de 12×12 1bpp (2 bytes/linha, 24 B/glifo).
- Mapa código→glifo: tabela ordenada de 2131 códigos SJIS em `0.BIN+0xB51A8` (busca binária).
  A fonte só tem os kanji usados pelo jogo; faltam b f j x z J Q Z no alfabeto fullwidth.
- Estratégia DTE (`yuno_dte.py`): cada célula 12×12 recebe **dois** caracteres ASCII de 6 px.
  Pares são atribuídos a códigos de kanji (dos mais raros para os mais comuns) e os glifos
  correspondentes são substituídos. 600 pares bastam para OPEN + menus.

## Menus do sistema
- Strings SJIS terminadas em NUL dentro de `0.BIN` (ex.: 0x169C0 "前回の続きから", 0x17418…,
  0x34898 "セーブ"). Substituídas no lugar com o mesmo encoding DTE (nunca maiores que o original).

## Pipeline
1. `tools/win_arc.py unpack MES.ARC …` (JP) e `zMES.ARC` (EN TLWiki) → `extracted/win_jp|win_eng`.
2. `tools/win_dict.py` → dicionário global JP→EN (52k mensagens).
3. `tools/align.py SENARIO.ABL NOME win_jp/NOME.MES win_eng/NOME.MES translations/scripts/NOME.json`
   (alinhamento por DP + fallback no dicionário global). Campo `en_edit` sobrepõe `en`.
4. `python tools/build_poc.py` → `build/Yuno Disc 1 (ENG PoC).bin/.cue` (+ ABLs, 0.BIN, pairs.png).

## Pendências conhecidas
- Ver se o motor pagina sozinho mensagens de 5 linhas (9 casos no OPEN).
- 59 scripts têm bytes `91` fora de textos (operandos); o scanner de textos é heurístico —
  conferir com o alinhamento Windows antes de traduzir cada script.
- Kanji "reaproveitados" para pares aparecem errados em textos ainda em japonês.
- Expressões do bytecode não estão totalmente decodificadas (não é necessário para texto).
- Próximo script após OPEN: `P10`.
