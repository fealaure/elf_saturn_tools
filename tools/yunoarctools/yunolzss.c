#include <string.h>

#define DLL_EXPORT 

#define DICT_SIZE  0x1000    // must be a power of 2
#define DICT_START 0xFEE

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

char version[] = "yunolzss 0.2";

static u8 dict[DICT_SIZE];


static void clear_dict() {
	memset(dict,0,DICT_SIZE);
}


// currently not used, since it can be done quite fast in straight Python
DLL_EXPORT int yuno_lazy_comp(u8 *out, u8 *in, int uncmprlen, int out_size) {

	int i,cmprlen=0;

	if(uncmprlen <= 0) goto done;
	if(out_size <= 0) goto fail;

	while(1) {
		*out++ = 0xFF;
		for(i=0; i<8; i++) {
			if(!uncmprlen--) goto done;
			if(cmprlen == out_size) goto fail;
			*out++ = *in++; cmprlen++;
		}
	}
	
	done:
	return cmprlen;
	
	fail:
	return -1;

}


// because Python is slow
DLL_EXPORT int yuno_decomp(u8 *out, u8 *in, int cmprlen, int out_size) {

	u8 data1,data2;
	u16 mask,dpos=DICT_START,idx;
	int i,n,uncmprlen=0;
	
	clear_dict();
	
	if(cmprlen <= 0) goto done;
	if(out_size <= 0) goto fail;
	
	while(1) {
		
		if(!cmprlen--) goto done; mask = 0xFF00 | *in++;
		
		while(mask & 0x100) {
		
			if(mask&1) {
		
				if(!cmprlen--) goto done;
				if(uncmprlen == out_size) goto fail;
				dict[dpos] = *out++ = *in++; uncmprlen++;
				dpos = (dpos + 1) & (DICT_SIZE-1);
			
			}
			else {
		
				if(!cmprlen--) goto done; data1 = *in++;
				if(!cmprlen--) goto done; data2 = *in++;
			

				n = (data2 & 0x0F) + 3;
			
				idx = ((data2 & 0xF0) << 4) | data1;
				
				for(i=0; i<n; i++) {
					if(uncmprlen == out_size) goto fail;
					dict[dpos] = *out++ = dict[(idx+i)&(DICT_SIZE-1)]; uncmprlen++;
					dpos = (dpos + 1) & (DICT_SIZE-1);
				}
			
			}
			mask >>= 1;
		}
	}
	
	done:
	return uncmprlen;
	
	fail:
	return -1;
}

