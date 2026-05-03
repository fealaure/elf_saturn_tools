#
# Yu-No windows ver. archive (.ARC) repacker
#

import glob
import io
import optparse
import os
import struct
import re
import fnmatch

version = '%prog 0.4'

# transparently compress the following file extensions
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

def csize(size,fname):
	if os.path.splitext(fname)[1].upper() in comp_ext:
		return size + (size+7)//8
	else:
		return size

def make_file_list(indir,options):
	fnames = []
	for fname in glob.glob(os.path.join(indir,'*')):
		sname = os.path.split(fname)[1]
		if fnmatch.fnmatch(sname,options.file) and re.match(options.regex,sname):
			fnames.append(fname)
	nfiles = len(fnames)
	sizes = [csize(os.path.getsize(fname),fname) for fname in fnames]
	offsets = [sum(sizes[:k])+28*nfiles+4 for k in range(nfiles)]
	fnames = [os.path.split(fname)[1] for fname in fnames]
	flist = list(zip(fnames,offsets,sizes))
	return flist

def lazy_compress(fo,fi):
	while 1:
		data = fi.read(8)
		if not data:
			break
		fo.write(b'\xFF')
		fo.write(data)
	
def pack(fo,indir,options):
	flist = make_file_list(indir,options)
	nfiles = len(flist)
	fo.write(struct.pack('<I',nfiles))
	for fname,offset,size in flist:
		fo.write(bytes([b^3 for b in fname.encode('ascii').ljust(20,b'\x00')]))
		fo.write(struct.pack('<I',size^0x33656755))
		fo.write(struct.pack('<I',offset^0x68820811))
	for id,finfo in enumerate(flist):
		fname,offset,size = finfo
		if options.verbose:
			print('%4d %s %08X %s' % (id,fname.ljust(15),offset,size_str(size)))
		fi = open(os.path.join(indir,fname),'rb')
		if os.path.splitext(fname)[1].upper() in comp_ext:
			lazy_compress(fo,fi)
		else:
			fo.write(fi.read())

def main():
	usage = 'usage: %prog [options] <input_dir> <arc_file>'
	parser = optparse.OptionParser(usage=usage,version=version)
	parser.add_option('-f','--file',dest='file',default='*',help='repack specific file named FILE (Unix-style wildcards accepted)')
	parser.add_option('-r','--regex',dest='regex',default='.+',help='filter repacked files using REGEX')
	parser.add_option('-v','--verbose',action='store_true',dest='verbose',help='verbose output')
	(options, args) = parser.parse_args()
	if len(args) < 2:
		parser.error('incorrect number of arguments')
		
	pack(open(args[1],'wb'),args[0],options)

if __name__ == '__main__':
	main()
