/* srt_hooks.c — libsrt workarounds (ADR 0012) and receiver-side SRT stats (ADR 0013).
 * The srt_* functions defined here replace the libsrt ones for libavformat:
 * ptzview is linked with -rdynamic so that they are exported. */
#include <dlfcn.h>

#include "ptzview.h"

/*
 * Workaround for libsrt 1.5.4 (Debian trixie): srt_startup() only counts its
 * first call (it returns early once the library runs) while every
 * srt_cleanup() decrements the count. FFmpeg calls both for each SRT input,
 * so the first input that closes or fails to connect shuts the whole library
 * down and breaks every other SRT connection of the process ("EID ... no
 * sockets to check"). ptzview defines srt_cleanup() as a no-op: the library
 * stays up while ptzview runs and the system frees it at exit. Linked with
 * -rdynamic so that libavformat calls this definition (ADR 0012).
 */
int srt_cleanup(void);
int srt_cleanup(void)
{
    return 0;
}

/*
 * Receiver-side SRT statistics (ADR 0013). FFmpeg does not give the libsrt
 * socket of an input, so ptzview defines srt_connect() (caller mode) and
 * srt_accept() (listener mode): they call the real libsrt functions and note
 * the socket in the input being opened. FFmpeg opens an input in the thread
 * that calls avformat_open_input(), so a per-thread variable tells which
 * input it is. Same -rdynamic mechanism as srt_cleanup() above.
 */
static __thread struct cam *opening_cam;

static void note_srt_sock(SRTSOCKET s)
{
    struct cam *c = opening_cam;
    if (!c || s == SRT_INVALID_SOCK)
        return;
    pthread_mutex_lock(&g.lock);
    c->srt_sock = s;
    pthread_mutex_unlock(&g.lock);
}

void forget_srt_sock(struct cam *c)
{
    pthread_mutex_lock(&g.lock);
    c->srt_sock = SRT_INVALID_SOCK;
    pthread_mutex_unlock(&g.lock);
}

int srt_connect(SRTSOCKET u, const struct sockaddr *name, int namelen)
{
    typedef int (*connect_fn)(SRTSOCKET, const struct sockaddr *, int);
    static connect_fn real;
    if (!real)
        real = (connect_fn)dlsym(RTLD_NEXT, "srt_connect");
    if (!real)
        return SRT_ERROR;
    int r = real(u, name, namelen);
    if (r != SRT_ERROR)
        note_srt_sock(u);
    return r;
}

SRTSOCKET srt_accept(SRTSOCKET u, struct sockaddr *addr, int *addrlen)
{
    typedef SRTSOCKET (*accept_fn)(SRTSOCKET, struct sockaddr *, int *);
    static accept_fn real;
    if (!real)
        real = (accept_fn)dlsym(RTLD_NEXT, "srt_accept");
    if (!real)
        return SRT_INVALID_SOCK;
    SRTSOCKET s = real(u, addr, addrlen);
    note_srt_sock(s);
    return s;
}

/* Input being opened by the calling thread (NULL once avformat_open_input() returned). */
void srt_hooks_opening(struct cam *c)
{
    opening_cam = c;
}

/* Receiver-side SRT figures of one input; counters are cumulative since the
 * connection started. A closed socket only makes srt_bistats() fail (libsrt
 * does not reuse socket ids). */
void srt_json(struct sbuf *s, SRTSOCKET sock)
{
    SRT_TRACEBSTATS p;
    if (sock == SRT_INVALID_SOCK || srt_bistats(sock, &p, 0, 1) == SRT_ERROR) {
        sb_printf(s, "null");
        return;
    }
    sb_printf(s,
              "{\"rtt_ms\":%.1f,\"recv_mbps\":%.2f,\"bandwidth_mbps\":%.1f,"
              "\"latency_ms\":%d,\"buffer_ms\":%d,\"packets\":%lld,\"lost\":%d,"
              "\"retrans\":%d,\"dropped\":%d,\"belated\":%lld}",
              p.msRTT, p.mbpsRecvRate, p.mbpsBandwidth, p.msRcvTsbPdDelay, p.msRcvBuf,
              (long long)p.pktRecvTotal, p.pktRcvLossTotal, p.pktRcvRetrans, p.pktRcvDropTotal,
              (long long)p.pktRcvBelated);
}
