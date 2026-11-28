PKGS   = libavformat libavcodec libavutil libdrm cairo libmicrohttpd srt
CFLAGS ?= -O2 -g -Wall -Wextra
CFLAGS += $(shell pkg-config --cflags $(PKGS))
LDLIBS += $(shell pkg-config --libs $(PKGS)) -lpthread -lm
# Export srt_cleanup(), srt_connect() and srt_accept() of ptzview to the shared
# libraries (libsrt workaround, ADR 0012; receiver SRT stats, ADR 0013).
LDFLAGS += -rdynamic

ptzview: ptzview.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f ptzview

.PHONY: clean
