/* util.c — time, log, threads, text buffer, JSON strings. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sched.h>

#include "ptzview.h"

int64_t now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}

static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;

void logm(const char *fmt, ...)
{
    struct timespec ts;
    struct tm tm;
    va_list ap;
    clock_gettime(CLOCK_REALTIME, &ts);
    localtime_r(&ts.tv_sec, &tm);
    pthread_mutex_lock(&log_lock);
    fprintf(stderr, "%02d:%02d:%02d.%03ld ", tm.tm_hour, tm.tm_min, tm.tm_sec,
            ts.tv_nsec / 1000000);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    pthread_mutex_unlock(&log_lock);
}

void sleep_ms(int ms)
{
    int64_t end = now_us() + (int64_t)ms * 1000;
    while (!g.quit && now_us() < end)
        usleep(50000);
}

void set_rt(void)
{
    if (g.cfg.rt_priority <= 0)
        return;
    struct sched_param sp = { .sched_priority = g.cfg.rt_priority };
    int r = pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    if (r)
        logm("rt_priority: %s (lancer en root ?)", strerror(r));
}


void sb_printf(struct sbuf *s, const char *fmt, ...)
{
    va_list ap;
    for (;;) {
        size_t room = s->cap - s->n;
        va_start(ap, fmt);
        int r = vsnprintf(s->b ? s->b + s->n : NULL, s->b ? room : 0, fmt, ap);
        va_end(ap);
        if (r < 0)
            return;
        if (s->b && (size_t)r < room) {
            s->n += r;
            return;
        }
        size_t nc = s->cap ? s->cap * 2 : 1024;
        while (nc < s->n + r + 1)
            nc *= 2;
        char *nb = realloc(s->b, nc);
        if (!nb)
            return;
        s->b = nb;
        s->cap = nc;
    }
}

void sb_json_str(struct sbuf *s, const char *str)
{
    sb_printf(s, "\"");
    for (const unsigned char *p = (const unsigned char *)str; *p; p++) {
        if (*p == '"' || *p == '\\')
            sb_printf(s, "\\%c", *p);
        else if (*p < 0x20)
            sb_printf(s, "\\u%04x", *p);
        else
            sb_printf(s, "%c", *p);
    }
    sb_printf(s, "\"");
}

/* nettoie un texte UMD : supprime les caractères de contrôle, tronque proprement en UTF-8 */
void clean_label(char *dst, const char *src)
{
    size_t n = 0;
    for (const unsigned char *p = (const unsigned char *)src; *p && n < LABEL_MAX - 1; p++)
        if (*p >= 0x20 && *p != 0x7f)
            dst[n++] = *p;
    if (n == LABEL_MAX - 1)
        while (n > 0 && ((unsigned char)dst[n] & 0xC0) == 0x80)
            n--;
    dst[n] = 0;
    while (n > 0 && dst[n - 1] == ' ')
        dst[--n] = 0;
}

const char *out_tag(int idx)
{
    static const char *const tags[] = { "sortie 1 : ", "sortie 2 : ", "sortie 3 : ",
                                        "sortie 4 : " };
    _Static_assert(sizeof tags / sizeof *tags == MAX_OUTPUTS, "one tag per output");
    return g.cfg.outputs > 1 && idx >= 0 && idx < MAX_OUTPUTS ? tags[idx] : "";
}
