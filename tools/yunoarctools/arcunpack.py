#
# Yu-No windows ver. archive (.ARC) unpacker
#

import io
import optparse
import os
import struct
import re
import fnmatch
import ctypes

version = '%prog 0.4'

# transparently decompress the following file extensions
comp_ext = ('.MES','.A6','.S4','.BIN')

def size_str(size):
	units = 'BKMGT'
	uidx = 0
	osize = size
	while 1:
		temp = size/1024
		if temp < 1:
			break
		size = temp
		uidx += 1
	if uidx == 0:
		return '%d%s' % (osize,units[uidx])
	else:
		return '%.2f%s' % (size,units[uidx])

def make_file_list(fi,nfiles):
	flist = []
	for id in range(nfiles):
		fname,size,offset = struct.unpack('<20sII',fi.read(28))
		fname = bytes([k^3 for k in fname]).rstrip(b'\x00').decode('ascii')
		size ^= 0x33656755
		offset ^= 0x68820811
		flist.append((fname,offset,size))
	return flist


#======================== begin terminally slow code =========================

def dwrite(fo,dict,dpos,b):
	dict[dpos] = b
	dpos = (dpos + 1) & 0xFFF
	fo.write(bytes([b]))
	return dict,dpos

# LZSS compression with a 0x1000-byte dictionary, meh
def slow_decomp(fo,bio):
	dict = bytearray(0x1000)
	dpos = 0xFEE    # weird place to start, but whatever...
	ipos = 0
	try:
		while 1:
			mask = bio.read(1)[0]
			for j in range(8):
				if mask&1:
					b = bio.read(1)[0]
					dict,dpos = dwrite(fo,dict,dpos,b)
				else:
					b1 = bio.read(1)[0]
					b2 = bio.read(1)[0]
					didx = ((b2&0xF0) << 4) | b1
					dnum = (b2 & 0xF) + 3
					for k in range(dnum):
						b = dict[didx]
						didx = (didx + 1) & 0xFFF
						dict,dpos = dwrite(fo,dict,dpos,b)
				mask >>= 1
	except IndexError:
		pass

#========================= end terminally slow code ==========================


# fast ctypes implementation of the above
# Windows only atm
def decomp(fo,bio):
	buf_size = 524288
	data = bio.read()
	c_cmprlen = ctypes.c_int(len(data))
	c_in = ctypes.create_string_buffer(data)
	# try 512 KB output buffer, then 1 MB, then 2MB
	for k in range(3):
		c_out_size = ctypes.c_int(buf_size)
		c_out = ctypes.create_string_buffer(c_out_size.value)
		uncmprlen = ctypes.cdll.yunolzss.yuno_decomp(c_out,c_in,c_cmprlen,c_out_size)
		if uncmprlen >= 0:
			break
		buf_size *= 2
	# three strikes and you're out!
	if uncmprlen == -1:
		raise MemoryError('yunolzss.dll - uncompressed data too large for output buffer')
	fo.write(c_out.raw[:uncmprlen])


def unpack(outdir,fi,options):
	nfiles = struct.unpack('<I',fi.read(4))[0]
	flist = make_file_list(fi,nfiles)
	for id,finfo in enumerate(flist):
		fname,offset,size = finfo
		if not fnmatch.fnmatch(fname,options.file):
			continue
		if not re.match(options.regex,fname):
			continue
		fi.seek(offset,os.SEEK_SET)
		data = fi.read(size)
		if options.verbose:
			print('%4d %s %08X %s' % (id,fname.ljust(15),offset,size_str(size)))
		if os.path.splitext(fname)[1].upper() in comp_ext:
			try:
				ctypes.cdll.yunolzss   # to trigger an exception (if needed)
				decomp(open(os.path.join(outdir,fname),'wb'),io.BytesIO(data))
			except WindowsError:
				slow_decomp(open(os.path.join(outdir,fname),'wb'),io.BytesIO(data))
		else:
			open(os.path.join(outdir,fname),'wb').write(data)

def main():
	usage = 'usage: %prog [options] <arc_file> <output_dir>'
	parser = optparse.OptionParser(usage=usage,version=version)
	parser.add_option('-f','--file',dest='file',default='*',help='unpack specific file named FILE (Unix-style wildcards accepted)')
	parser.add_option('-r','--regex',dest='regex',default='.+',help='filter unpacked files using REGEX')
	parser.add_option('-v','--verbose',action='store_true',dest='verbose',help='verbose output')
	(options, args) = parser.parse_args()
	if len(args) < 2:
		parser.error('incorrect number of arguments')
		
	if not os.access(args[1],os.F_OK):
		os.mkdir(args[1])
	unpack(args[1],open(args[0],'rb'),options)

if __name__ == '__main__':
	main()
