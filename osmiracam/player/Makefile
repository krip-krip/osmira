PKGS   = libavformat libavcodec libavutil libdrm cairo libmicrohttpd
CFLAGS ?= -O2 -g -Wall -Wextra
CFLAGS += $(shell pkg-config --cflags $(PKGS))
LDLIBS += $(shell pkg-config --libs $(PKGS)) -lpthread -lm
# Export srt_cleanup() of ptzview to the shared libraries (libsrt workaround).
LDFLAGS += -rdynamic

ptzview: ptzview.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f ptzview

.PHONY: clean
