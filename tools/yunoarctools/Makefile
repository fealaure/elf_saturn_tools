CC     = gcc
LD     = gcc
CPP    = g++
INCS   = 
CFLAGS = $(INCS) -O3
RM     = rm -f

RES  =
OBJ  =   yunolzss.o 
OBJ +=   $(RES)

LINKOBJ = $(OBJ) 
LIBS    = 
LFLAGS  = -s

BIN  = yunolzss.dll

.PHONY: all all-before all-after clean clean-custom

all: all-before yunolzss.dll all-after

clean: clean-custom
	${RM} $(OBJ) $(BIN)

DLLWRAP   = dllwrap
DEFFILE   = yunolzss.def

$(BIN): $(LINKOBJ)
	$(DLLWRAP) --def $(DEFFILE) $(LINKOBJ) $(LIBS) $(LFLAGS) -o $(BIN)

yunolzss.o: yunolzss.c
	$(CC) -c yunolzss.c -o yunolzss.o $(CFLAGS)
