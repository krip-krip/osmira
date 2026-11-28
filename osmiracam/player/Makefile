PKGS   = libavformat libavcodec libavutil libdrm cairo libmicrohttpd srt
CFLAGS ?= -O2 -g -Wall -Wextra
CFLAGS += $(shell pkg-config --cflags $(PKGS))
# -MMD -MP: each .o gets a .d file listing the headers it uses, so that
# changing a header rebuilds the modules that include it.
CPPFLAGS += -D_GNU_SOURCE -MMD -MP
LDLIBS += $(shell pkg-config --libs $(PKGS)) -lpthread -lm
# Export srt_cleanup(), srt_connect() and srt_accept() of ptzview to the shared
# libraries (libsrt workaround, ADR 0012; receiver SRT stats, ADR 0013).
LDFLAGS += -rdynamic

SRCS = $(addprefix src/, main.c util.c sysinfo.c config.c srt_hooks.c input.c \
                         kms.c osd.c display.c http.c)
OBJS = $(SRCS:.c=.o)

ptzview: $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJS) $(LDLIBS)

-include $(OBJS:.o=.d)

clean:
	rm -f ptzview src/*.o src/*.d

.PHONY: clean
