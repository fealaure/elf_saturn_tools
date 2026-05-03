YU-NO arctools
author: kingshriek
version: 0.4

arcunpack.py     archive (.ARC) unpacker
arcrepack.py     archive (.ARC) repacker

The tools only support the Windows (Elf Classics) release of the game.
All tools are Python 3.x scripts (they will not work with Python 2.x).
Feel free to contact me at either #tlwiki@irc.rizon.net or my tlwiki User
Talk page (User:Kingshriek) regarding bugs/usage.



arcunpack.py:

Unpacks a archive file into a directory of your choosing. Files with the
extension .MES, .BIN, .A6, .S4 that occur inside archives are decompressed 
by the tool, all other files are just extracted straight.

For fast decompression, arcunpack.py uses an external dll, yunolzss.dll. As
a fallback, it will use a terminally slow routine in straight Python that
does the same thing. 

Usage: arcunpack.py [options] <arc_file> <output_dir>

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -f FILE, --file=FILE  unpack specific file named FILE (Unix-style wildcards
                        accepted)
  -r REGEX, --regex=REGEX
                        filter unpacked files using REGEX
  -v, --verbose         verbose output



arcrepack.py:

Packs files in a specified directory into an archive that YU-NO can use.

For .MES (as well as .BIN, .A6, .S4) files, this performs what I call 
"lazy compression". This is where the dictionary is ignored, and all bytes are 
just pass through straight. Actually, the .MES files are actually packed in at
a larger size since they also include mask bytes that determine whether to 
read from the dictionary or not. At least this "lazy compression" can be done 
fairly quickly in straight Python.

Usage: arcrepack.py [options] <input_dir> <arc_file>

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -f FILE, --file=FILE  repack specific file named FILE (Unix-style wildcards
                        accepted)
  -r REGEX, --regex=REGEX
                        filter repacked files using REGEX
  -v, --verbose         verbose output
