PKGS   = libavformat libavcodec libavutil libdrm cairo libmicrohttpd
CFLAGS ?= -O2 -g -Wall -Wextra
CFLAGS += $(shell pkg-config --cflags $(PKGS))
LDLIBS += $(shell pkg-config --libs $(PKGS)) -lpthread -lm

ptzview: ptzview.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f ptzview

.PHONY: clean
