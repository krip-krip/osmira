/*
 * ptzview — lecteur 4 x SRT/HEVC pour Raspberry Pi 4 (maquette)
 *
 *  - 4 entrées SRT (MPEG-TS/HEVC) reçues et décodées en permanence
 *    (FFmpeg "+rpt", hwaccel drm -> images DRM PRIME, zéro copie)
 *  - affichage DRM/KMS atomique : la caméra choisie sur un plan vidéo,
 *    tally + UMD + NO SIGNAL sur un plan ARGB au-dessus (redessiné
 *    seulement quand l'état change)
 *  - API HTTP (libmicrohttpd) : sélection, texte, tally, état JSON
 *
 * Usage : ptzview [-n] [fichier.conf]
 *   -n : pas d'affichage (décodage + API seulement, pour diagnostic)
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include <drm_fourcc.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_drm.h>

#include <cairo.h>
#include <microhttpd.h>

#define NCAM 4
#define LABEL_MAX 96
#define MAX_PLANES 32

/* ------------------------------------------------------------------ */
/* Types et état global                                                */
/* ------------------------------------------------------------------ */

typedef enum { TALLY_OFF = 0, TALLY_PVW, TALLY_PGM } tally_t;
static const char *tally_name[] = { "off", "pvw", "pgm" };

typedef enum { ST_CONNECTING = 0, ST_CONNECTED, ST_STREAMING, ST_WAITING } cstate_t;
static const char *state_name[] = { "connecting", "connected", "streaming", "waiting" };

struct cam {
    int idx;
    char url[512];
    /* protégé par g.lock */
    char label[LABEL_MAX];
    tally_t tally;
    cstate_t state;
    AVFrame *latest;          /* dernière image décodée (DRM PRIME) */
    uint64_t seq;             /* incrémenté à chaque nouvelle image */
    int64_t last_frame_us;
    double fps, mbps;
    int width, height;
    unsigned connects, decode_errors;
    char last_error[160];
    /* privé au thread de la caméra */
    pthread_t th;
    volatile int64_t deadline_us;
    char prev_err[160];
    int64_t prev_err_log_us;
};

struct config {
    int srt_latency_ms, connect_timeout_ms, stall_timeout_ms, reconnect_ms;
    char hwaccel[32], hwaccel_device[128];
    int extra_hw_frames;
    char drm_device[64], connector[32], hdmi_mode[32], video_plane[16];
    int http_port, start_camera;
    char font[64];
    double umd_off_alpha;
    int stats_interval_s, rt_priority;
    char loglevel[16];
};

static struct {
    struct config cfg;
    struct cam cam[NCAM];
    pthread_mutex_t lock;
    pthread_cond_t cond;
    int selected;             /* 0..3 */
    int64_t switch_req_us;
    double last_switch_ms;
    volatile sig_atomic_t quit;
    bool no_display;
    AVBufferRef *hwdev;
    int64_t start_us;
    char output_desc[64];
} g;

/* ------------------------------------------------------------------ */
/* Outils                                                              */
/* ------------------------------------------------------------------ */

static int64_t now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}

static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;

static void logm(const char *fmt, ...)
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

static void sleep_ms(int ms)
{
    int64_t end = now_us() + (int64_t)ms * 1000;
    while (!g.quit && now_us() < end)
        usleep(50000);
}

static void set_rt(void)
{
    if (g.cfg.rt_priority <= 0)
        return;
    struct sched_param sp = { .sched_priority = g.cfg.rt_priority };
    int r = pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    if (r)
        logm("rt_priority: %s (lancer en root ?)", strerror(r));
}

static long meminfo_kb(const char *key)
{
    FILE *f = fopen("/proc/meminfo", "r");
    char line[128];
    long v = -1;
    size_t kl = strlen(key);
    if (!f)
        return -1;
    while (fgets(line, sizeof line, f))
        if (!strncmp(line, key, kl) && line[kl] == ':') {
            v = strtol(line + kl + 1, NULL, 10);
            break;
        }
    fclose(f);
    return v;
}

static double soc_temp(void)
{
    FILE *f = fopen("/sys/class/thermal/thermal_zone0/temp", "r");
    long v = 0;
    if (!f)
        return -1;
    if (fscanf(f, "%ld", &v) != 1)
        v = -1000;
    fclose(f);
    return v / 1000.0;
}

/* tampon de texte extensible */
struct sbuf { char *b; size_t n, cap; };

static void sb_printf(struct sbuf *s, const char *fmt, ...)
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

static void sb_json_str(struct sbuf *s, const char *str)
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
static void clean_label(char *dst, const char *src)
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

/* ------------------------------------------------------------------ */
/* Configuration                                                       */
/* ------------------------------------------------------------------ */

static void config_defaults(void)
{
    struct config *c = &g.cfg;
    c->srt_latency_ms = 20;
    c->connect_timeout_ms = 1500;
    c->stall_timeout_ms = 1000;
    c->reconnect_ms = 2000;
    strcpy(c->hwaccel, "drm");
    c->hwaccel_device[0] = 0;
    c->extra_hw_frames = 2;
    strcpy(c->drm_device, "auto");
    strcpy(c->connector, "HDMI-A-1");
    strcpy(c->hdmi_mode, "1920x1080@50");
    strcpy(c->video_plane, "auto");
    c->http_port = 8080;
    c->start_camera = 1;
    strcpy(c->font, "DejaVu Sans");
    c->umd_off_alpha = 0.30;
    c->stats_interval_s = 10;
    c->rt_priority = 0;
    strcpy(c->loglevel, "error");
    for (int i = 0; i < NCAM; i++) {
        struct cam *cm = &g.cam[i];
        cm->idx = i;
        snprintf(cm->url, sizeof cm->url,
                 "srt://192.168.104.253:8890?mode=caller&streamid=read:cam%d", i + 1);
        snprintf(cm->label, sizeof cm->label, "CAM %d", i + 1);
        cm->tally = TALLY_OFF;
    }
}

static char *trim(char *s)
{
    while (isspace((unsigned char)*s))
        s++;
    char *e = s + strlen(s);
    while (e > s && isspace((unsigned char)e[-1]))
        *--e = 0;
    return s;
}

static void unquote(char *s)
{
    size_t n = strlen(s);
    if (n >= 2 && ((s[0] == '"' && s[n - 1] == '"') || (s[0] == '\'' && s[n - 1] == '\''))) {
        memmove(s, s + 1, n - 2);
        s[n - 2] = 0;
    }
}

static int parse_tally(const char *s)
{
    for (int i = 0; i < 3; i++)
        if (!strcasecmp(s, tally_name[i]))
            return i;
    return -1;
}

#define CFG_INT(name) if (!strcmp(k, #name)) { c->name = atoi(v); return 0; }
#define CFG_DBL(name) if (!strcmp(k, #name)) { c->name = atof(v); return 0; }
#define CFG_STR(name) if (!strcmp(k, #name)) { snprintf(c->name, sizeof c->name, "%s", v); return 0; }

static int set_general(const char *k, const char *v)
{
    struct config *c = &g.cfg;
    CFG_INT(srt_latency_ms) CFG_INT(connect_timeout_ms) CFG_INT(stall_timeout_ms)
    CFG_INT(reconnect_ms) CFG_STR(hwaccel) CFG_STR(hwaccel_device) CFG_INT(extra_hw_frames)
    CFG_STR(drm_device) CFG_STR(connector) CFG_STR(hdmi_mode) CFG_STR(video_plane)
    CFG_INT(http_port) CFG_INT(start_camera) CFG_STR(font) CFG_DBL(umd_off_alpha)
    CFG_INT(stats_interval_s) CFG_INT(rt_priority) CFG_STR(loglevel)
    return -1;
}

static int load_config(const char *path)
{
    FILE *f = fopen(path, "r");
    char line[1024], sect[32] = "";
    int ln = 0;
    if (!f) {
        logm("config : impossible d'ouvrir %s : %s", path, strerror(errno));
        return -1;
    }
    while (fgets(line, sizeof line, f)) {
        ln++;
        char *s = trim(line);
        if (!*s || *s == '#' || *s == ';')
            continue;
        if (*s == '[') {
            char *e = strchr(s, ']');
            if (e)
                *e = 0;
            snprintf(sect, sizeof sect, "%s", trim(s + 1));
            continue;
        }
        char *eq = strchr(s, '=');
        if (!eq) {
            logm("config:%d : ligne ignorée", ln);
            continue;
        }
        *eq = 0;
        char *k = trim(s), *v = trim(eq + 1);
        unquote(v);
        if (!strcmp(sect, "general")) {
            if (set_general(k, v) < 0)
                logm("config:%d : clé inconnue « %s »", ln, k);
        } else if (!strncmp(sect, "cam", 3) && sect[3] >= '1' && sect[3] <= '4' && !sect[4]) {
            struct cam *c = &g.cam[sect[3] - '1'];
            if (!strcmp(k, "url"))
                snprintf(c->url, sizeof c->url, "%s", v);
            else if (!strcmp(k, "label"))
                clean_label(c->label, v);
            else if (!strcmp(k, "tally")) {
                int t = parse_tally(v);
                if (t < 0)
                    logm("config:%d : tally « %s » invalide (off/pvw/pgm)", ln, v);
                else
                    c->tally = t;
            } else
                logm("config:%d : clé inconnue « %s »", ln, k);
        } else
            logm("config:%d : section inconnue [%s]", ln, sect);
    }
    fclose(f);
    if (g.cfg.start_camera < 1 || g.cfg.start_camera > NCAM)
        g.cfg.start_camera = 1;
    return 0;
}

/* ------------------------------------------------------------------ */
/* Entrées : réception SRT + décodage HEVC matériel                    */
/* ------------------------------------------------------------------ */

static int interrupt_cb(void *opaque)
{
    struct cam *c = opaque;
    if (g.quit)
        return 1;
    return c->deadline_us && now_us() > c->deadline_us;
}

static enum AVPixelFormat get_hw_format(AVCodecContext *ctx, const enum AVPixelFormat *fmts)
{
    struct cam *c = ctx->opaque;
    for (const enum AVPixelFormat *p = fmts; *p != AV_PIX_FMT_NONE; p++)
        if (*p == AV_PIX_FMT_DRM_PRIME)
            return *p;
    logm("cam%d : le décodeur ne propose pas DRM_PRIME (hwaccel indisponible ?)", c->idx + 1);
    return AV_PIX_FMT_NONE;
}

static void cam_error(struct cam *c, const char *what, int err)
{
    char e[96], msg[160];
    av_strerror(err, e, sizeof e);
    snprintf(msg, sizeof msg, "%s : %s", what, e);
    pthread_mutex_lock(&g.lock);
    snprintf(c->last_error, sizeof c->last_error, "%s", msg);
    pthread_mutex_unlock(&g.lock);
    /* évite de remplir le terminal pendant une coupure longue */
    int64_t t = now_us();
    if (strcmp(msg, c->prev_err) || t - c->prev_err_log_us > 30000000) {
        logm("cam%d : %s", c->idx + 1, msg);
        snprintf(c->prev_err, sizeof c->prev_err, "%s", msg);
        c->prev_err_log_us = t;
    }
}

static void cam_set_state(struct cam *c, cstate_t st)
{
    pthread_mutex_lock(&g.lock);
    c->state = st;
    if (st != ST_STREAMING)
        c->fps = c->mbps = 0;
    pthread_cond_broadcast(&g.cond);
    pthread_mutex_unlock(&g.lock);
}

static AVCodecContext *open_decoder(struct cam *c, AVStream *st)
{
    const AVCodec *codec = avcodec_find_decoder(st->codecpar->codec_id);
    if (!codec)
        return NULL;
    AVCodecContext *d = avcodec_alloc_context3(codec);
    if (!d)
        return NULL;
    avcodec_parameters_to_context(d, st->codecpar);
    d->opaque = c;
    d->get_format = get_hw_format;
    if (g.hwdev)
        d->hw_device_ctx = av_buffer_ref(g.hwdev);
    d->flags |= AV_CODEC_FLAG_LOW_DELAY;
    d->thread_count = 1;                 /* pas de frame-threading : pas d'image de retard */
    d->extra_hw_frames = g.cfg.extra_hw_frames;
    d->pkt_timebase = st->time_base;
    int r = avcodec_open2(d, codec, NULL);
    if (r < 0) {
        cam_error(c, "ouverture décodeur", r);
        avcodec_free_context(&d);
        return NULL;
    }
    return d;
}

static void publish_frame(struct cam *c, AVFrame *frm)
{
    pthread_mutex_lock(&g.lock);
    if (!c->latest)
        c->latest = av_frame_alloc();
    else
        av_frame_unref(c->latest);
    av_frame_move_ref(c->latest, frm);
    c->seq++;
    c->last_frame_us = now_us();
    c->width = c->latest->width;
    c->height = c->latest->height;
    bool wake = (c->idx == g.selected) || c->state != ST_STREAMING;
    c->state = ST_STREAMING;
    if (wake)
        pthread_cond_broadcast(&g.cond);
    pthread_mutex_unlock(&g.lock);
}

static void *cam_thread(void *arg)
{
    struct cam *c = arg;
    char name[16];
    snprintf(name, sizeof name, "cam%d", c->idx + 1);
    pthread_setname_np(pthread_self(), name);
    set_rt();

    AVPacket *pkt = av_packet_alloc();
    AVFrame *frm = av_frame_alloc();
    const AVInputFormat *ts = av_find_input_format("mpegts");
    bool first = true, warned_fmt = false;

    while (!g.quit) {
        if (!first) {
            cam_set_state(c, ST_WAITING);
            sleep_ms(g.cfg.reconnect_ms);
            if (g.quit)
                break;
        }
        first = false;
        cam_set_state(c, ST_CONNECTING);

        AVFormatContext *fmt = avformat_alloc_context();
        AVCodecContext *dec = NULL;
        AVDictionary *opt = NULL;
        int vidx = -1, r;

        fmt->interrupt_callback.callback = interrupt_cb;
        fmt->interrupt_callback.opaque = c;
        fmt->flags |= AVFMT_FLAG_NOBUFFER;
        fmt->probesize = 128 * 1024;
        /* options SRT de FFmpeg : latency en MICROsecondes, connect_timeout en ms */
        av_dict_set_int(&opt, "latency", (int64_t)g.cfg.srt_latency_ms * 1000, 0);
        av_dict_set_int(&opt, "connect_timeout", g.cfg.connect_timeout_ms, 0);
        av_dict_set(&opt, "transtype", "live", 0);

        c->deadline_us = now_us() + (int64_t)(g.cfg.connect_timeout_ms + 2000) * 1000;
        r = avformat_open_input(&fmt, c->url, ts, &opt);
        av_dict_free(&opt);
        if (r < 0) {
            cam_error(c, "connexion", r);
            continue;
        }
        pthread_mutex_lock(&g.lock);
        c->state = ST_CONNECTED;
        c->connects++;
        pthread_cond_broadcast(&g.cond);
        pthread_mutex_unlock(&g.lock);
        logm("cam%d : connecté (%s)", c->idx + 1, c->url);
        c->prev_err[0] = 0;

        int64_t win_start = now_us();
        unsigned win_frames = 0;
        uint64_t win_bytes = 0;

        while (!g.quit) {
            c->deadline_us = now_us() + (int64_t)g.cfg.stall_timeout_ms * 1000;
            r = av_read_frame(fmt, pkt);
            if (r < 0) {
                cam_error(c, r == AVERROR_EXIT ? "plus de données (timeout)" : "lecture", r);
                break;
            }
            if (vidx < 0) {
                AVStream *st = fmt->streams[pkt->stream_index];
                if (st->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                    if (st->codecpar->codec_id != AV_CODEC_ID_HEVC)
                        logm("cam%d : codec %s (attendu : HEVC)", c->idx + 1,
                             avcodec_get_name(st->codecpar->codec_id));
                    dec = open_decoder(c, st);
                    if (!dec) {
                        r = AVERROR(EINVAL);
                        break;
                    }
                    vidx = pkt->stream_index;
                }
            }
            if (pkt->stream_index != vidx) {
                fmt->streams[pkt->stream_index]->discard = AVDISCARD_ALL;
                av_packet_unref(pkt);
                continue;
            }
            win_bytes += pkt->size;
            r = avcodec_send_packet(dec, pkt);
            av_packet_unref(pkt);
            if (r < 0 && r != AVERROR(EAGAIN)) {
                if (r == AVERROR_INVALIDDATA) {
                    pthread_mutex_lock(&g.lock);
                    c->decode_errors++;
                    pthread_mutex_unlock(&g.lock);
                    continue;
                }
                cam_error(c, "décodage", r);
                break;
            }
            bool fatal = false;
            for (;;) {
                r = avcodec_receive_frame(dec, frm);
                if (r == AVERROR(EAGAIN) || r == AVERROR_EOF)
                    break;
                if (r < 0) {
                    if (r == AVERROR_INVALIDDATA) {
                        pthread_mutex_lock(&g.lock);
                        c->decode_errors++;
                        pthread_mutex_unlock(&g.lock);
                        break;
                    }
                    cam_error(c, "décodage", r);
                    fatal = true;
                    break;
                }
                if (frm->format != AV_PIX_FMT_DRM_PRIME) {
                    if (!warned_fmt)
                        logm("cam%d : image non DRM_PRIME (décodage logiciel ?) : ignorée",
                             c->idx + 1);
                    warned_fmt = true;
                    av_frame_unref(frm);
                    continue;
                }
                win_frames++;
                publish_frame(c, frm);
            }
            if (fatal)
                break;
            int64_t t = now_us();
            if (t - win_start >= 1000000) {
                pthread_mutex_lock(&g.lock);
                c->fps = win_frames * 1e6 / (t - win_start);
                c->mbps = win_bytes * 8.0 / (t - win_start);
                pthread_mutex_unlock(&g.lock);
                win_start = t;
                win_frames = 0;
                win_bytes = 0;
            }
        }
        avcodec_free_context(&dec);
        avformat_close_input(&fmt);
        if (!g.quit)
            logm("cam%d : déconnecté, nouvel essai dans %d ms", c->idx + 1, g.cfg.reconnect_ms);
    }
    av_packet_free(&pkt);
    av_frame_free(&frm);
    return NULL;
}

/* ------------------------------------------------------------------ */
/* Affichage DRM/KMS                                                   */
/* ------------------------------------------------------------------ */

struct plane_info {
    uint32_t id;
    int type;                      /* 0 overlay, 1 primary, 2 cursor */
    bool nv12, argb;
    uint32_t fb_id, crtc_id, src_x, src_y, src_w, src_h, crtc_x, crtc_y, crtc_w, crtc_h;
    uint32_t zpos, color_enc, color_range;
    uint64_t zmin, zmax;
    uint64_t enc601, enc709, enc2020, rng_lim, rng_full;
    bool has_601, has_709, has_2020, has_lim, has_full;
};

struct dumb { uint32_t handle, pitch, fb; uint64_t size; uint8_t *map; };

static struct {
    int fd;
    uint32_t conn, crtc;
    int crtc_idx;
    drmModeModeInfo mode;
    uint32_t mode_blob;
    uint32_t conn_crtc_prop, crtc_mode_prop, crtc_active_prop;
    struct plane_info pl[MAX_PLANES];
    int npl;
    int vp, op;                    /* indices dans pl[] des plans vidéo / OSD */
    int disable_pending;           /* plan à désactiver au prochain commit, -1 sinon */
    bool video_ok, osd_force;
    int w, h;
    struct dumb ov[2];
    int ov_cur;
    cairo_surface_t *surf;
} k = { .fd = -1, .vp = -1, .op = -1, .disable_pending = -1 };

static void load_plane(struct plane_info *p)
{
    drmModeObjectProperties *pr = drmModeObjectGetProperties(k.fd, p->id, DRM_MODE_OBJECT_PLANE);
    if (!pr)
        return;
    for (uint32_t i = 0; i < pr->count_props; i++) {
        drmModePropertyRes *q = drmModeGetProperty(k.fd, pr->props[i]);
        if (!q)
            continue;
        const char *n = q->name;
        uint32_t id = q->prop_id;
        if (!strcmp(n, "type")) p->type = (int)pr->prop_values[i];
        else if (!strcmp(n, "FB_ID")) p->fb_id = id;
        else if (!strcmp(n, "CRTC_ID")) p->crtc_id = id;
        else if (!strcmp(n, "SRC_X")) p->src_x = id;
        else if (!strcmp(n, "SRC_Y")) p->src_y = id;
        else if (!strcmp(n, "SRC_W")) p->src_w = id;
        else if (!strcmp(n, "SRC_H")) p->src_h = id;
        else if (!strcmp(n, "CRTC_X")) p->crtc_x = id;
        else if (!strcmp(n, "CRTC_Y")) p->crtc_y = id;
        else if (!strcmp(n, "CRTC_W")) p->crtc_w = id;
        else if (!strcmp(n, "CRTC_H")) p->crtc_h = id;
        else if (!strcmp(n, "zpos") && !(q->flags & DRM_MODE_PROP_IMMUTABLE)) {
            p->zpos = id;
            if (q->count_values >= 2) {
                p->zmin = q->values[0];
                p->zmax = q->values[1];
            }
        } else if (!strcmp(n, "COLOR_ENCODING")) {
            p->color_enc = id;
            for (int j = 0; j < q->count_enums; j++) {
                if (strstr(q->enums[j].name, "601")) { p->enc601 = q->enums[j].value; p->has_601 = true; }
                if (strstr(q->enums[j].name, "709")) { p->enc709 = q->enums[j].value; p->has_709 = true; }
                if (strstr(q->enums[j].name, "2020")) { p->enc2020 = q->enums[j].value; p->has_2020 = true; }
            }
        } else if (!strcmp(n, "COLOR_RANGE")) {
            p->color_range = id;
            for (int j = 0; j < q->count_enums; j++) {
                if (strstr(q->enums[j].name, "limited")) { p->rng_lim = q->enums[j].value; p->has_lim = true; }
                if (strstr(q->enums[j].name, "full")) { p->rng_full = q->enums[j].value; p->has_full = true; }
            }
        }
        drmModeFreeProperty(q);
    }
    drmModeFreeObjectProperties(pr);
}

static uint32_t obj_prop(uint32_t obj, uint32_t type, const char *name)
{
    drmModeObjectProperties *pr = drmModeObjectGetProperties(k.fd, obj, type);
    uint32_t id = 0;
    if (!pr)
        return 0;
    for (uint32_t i = 0; i < pr->count_props && !id; i++) {
        drmModePropertyRes *q = drmModeGetProperty(k.fd, pr->props[i]);
        if (q && !strcmp(q->name, name))
            id = q->prop_id;
        drmModeFreeProperty(q);
    }
    drmModeFreeObjectProperties(pr);
    return id;
}

static void add(drmModeAtomicReq *r, uint32_t obj, uint32_t prop, uint64_t v)
{
    if (prop)
        drmModeAtomicAddProperty(r, obj, prop, v);
}

static void plane_disable(drmModeAtomicReq *r, const struct plane_info *p)
{
    add(r, p->id, p->fb_id, 0);
    add(r, p->id, p->crtc_id, 0);
}

static void plane_full(drmModeAtomicReq *r, const struct plane_info *p, uint32_t fb,
                       int sw, int sh, int dx, int dy, int dw, int dh)
{
    add(r, p->id, p->fb_id, fb);
    add(r, p->id, p->crtc_id, k.crtc);
    add(r, p->id, p->src_x, 0);
    add(r, p->id, p->src_y, 0);
    add(r, p->id, p->src_w, (uint64_t)sw << 16);
    add(r, p->id, p->src_h, (uint64_t)sh << 16);
    add(r, p->id, p->crtc_x, dx);
    add(r, p->id, p->crtc_y, dy);
    add(r, p->id, p->crtc_w, dw);
    add(r, p->id, p->crtc_h, dh);
}

static void set_osd(drmModeAtomicReq *r, int op, uint32_t fb)
{
    const struct plane_info *p = &k.pl[op];
    plane_full(r, p, fb, k.w, k.h, 0, 0, k.w, k.h);
    if (p->zpos)
        add(r, p->id, p->zpos, p->zmax);
}

static void set_video(drmModeAtomicReq *r, int vp, uint32_t fb, const AVFrame *f)
{
    const struct plane_info *p = &k.pl[vp];
    int sw = f->width, sh = f->height, dw, dh;
    /* conserve le rapport d'image */
    if ((int64_t)sw * k.h > (int64_t)sh * k.w) {
        dw = k.w;
        dh = (int)((int64_t)k.w * sh / sw);
    } else {
        dh = k.h;
        dw = (int)((int64_t)k.h * sw / sh);
    }
    plane_full(r, p, fb, sw, sh, (k.w - dw) / 2, (k.h - dh) / 2, dw, dh);
    if (p->zpos)
        add(r, p->id, p->zpos, p->zmin);
    if (p->color_enc) {
        if (f->colorspace == AVCOL_SPC_BT2020_NCL && p->has_2020)
            add(r, p->id, p->color_enc, p->enc2020);
        else if ((f->colorspace == AVCOL_SPC_BT470BG || f->colorspace == AVCOL_SPC_SMPTE170M) &&
                 p->has_601)
            add(r, p->id, p->color_enc, p->enc601);
        else if (p->has_709)
            add(r, p->id, p->color_enc, p->enc709);
    }
    if (p->color_range) {
        if (f->color_range == AVCOL_RANGE_JPEG && p->has_full)
            add(r, p->id, p->color_range, p->rng_full);
        else if (p->has_lim)
            add(r, p->id, p->color_range, p->rng_lim);
    }
}

static int dumb_create(struct dumb *d)
{
    struct drm_mode_create_dumb c = { .width = k.w, .height = k.h, .bpp = 32 };
    if (drmIoctl(k.fd, DRM_IOCTL_MODE_CREATE_DUMB, &c))
        return -1;
    d->handle = c.handle;
    d->pitch = c.pitch;
    d->size = c.size;
    uint32_t h[4] = { c.handle }, p[4] = { c.pitch }, o[4] = { 0 };
    if (drmModeAddFB2(k.fd, k.w, k.h, DRM_FORMAT_ARGB8888, h, p, o, &d->fb, 0))
        return -1;
    struct drm_mode_map_dumb m = { .handle = c.handle };
    if (drmIoctl(k.fd, DRM_IOCTL_MODE_MAP_DUMB, &m))
        return -1;
    d->map = mmap(NULL, c.size, PROT_READ | PROT_WRITE, MAP_SHARED, k.fd, m.offset);
    if (d->map == MAP_FAILED) {
        d->map = NULL;
        return -1;
    }
    memset(d->map, 0, c.size);
    return 0;
}

static void dumb_destroy(struct dumb *d)
{
    if (d->map)
        munmap(d->map, d->size);
    if (d->fb)
        drmModeRmFB(k.fd, d->fb);
    if (d->handle) {
        struct drm_mode_destroy_dumb x = { .handle = d->handle };
        drmIoctl(k.fd, DRM_IOCTL_MODE_DESTROY_DUMB, &x);
    }
    memset(d, 0, sizeof *d);
}

static const char *conn_name(drmModeConnector *c, char *buf, size_t n)
{
    const char *t = drmModeGetConnectorTypeName(c->connector_type);
    snprintf(buf, n, "%s-%u", t ? t : "?", c->connector_type_id);
    return buf;
}

static bool pick_mode(drmModeConnector *c, drmModeModeInfo *out)
{
    const char *m = g.cfg.hdmi_mode;
    int w = 0, h = 0, hz = 0;
    if (!strcasecmp(m, "auto")) {
        for (int i = 0; i < c->count_modes; i++)
            if (c->modes[i].type & DRM_MODE_TYPE_PREFERRED) {
                *out = c->modes[i];
                return true;
            }
        if (c->count_modes) {
            *out = c->modes[0];
            return true;
        }
        return false;
    }
    if (strspn(m, "0123456789") == strlen(m)) {
        int i = atoi(m);
        if (i >= 0 && i < c->count_modes) {
            *out = c->modes[i];
            return true;
        }
        return false;
    }
    if (sscanf(m, "%dx%d@%d", &w, &h, &hz) < 2)
        return false;
    for (int i = 0; i < c->count_modes; i++) {
        drmModeModeInfo *x = &c->modes[i];
        if (x->hdisplay == w && x->vdisplay == h && !(x->flags & DRM_MODE_FLAG_INTERLACE) &&
            (!hz || (int)x->vrefresh == hz)) {
            *out = *x;
            return true;
        }
    }
    return false;
}

static int kms_init(void)
{
    char path[64], name[32];
    drmModeRes *res = NULL;

    for (int i = 0; i < 8; i++) {
        if (strcmp(g.cfg.drm_device, "auto"))
            snprintf(path, sizeof path, "%s", g.cfg.drm_device);
        else
            snprintf(path, sizeof path, "/dev/dri/card%d", i);
        int fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd >= 0) {
            res = drmModeGetResources(fd);
            if (res && res->count_connectors && res->count_crtcs) {
                k.fd = fd;
                break;
            }
            if (res)
                drmModeFreeResources(res);
            res = NULL;
            close(fd);
        }
        if (strcmp(g.cfg.drm_device, "auto"))
            break;
    }
    if (k.fd < 0) {
        logm("DRM : aucune carte d'affichage trouvée (drm_device=%s)", g.cfg.drm_device);
        return -1;
    }
    if (drmSetClientCap(k.fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1) ||
        drmSetClientCap(k.fd, DRM_CLIENT_CAP_ATOMIC, 1)) {
        logm("DRM : mode atomique non disponible");
        return -1;
    }

    /* connecteur */
    drmModeConnector *conn = NULL;
    for (int i = 0; i < res->count_connectors && !conn; i++) {
        drmModeConnector *c = drmModeGetConnector(k.fd, res->connectors[i]);
        if (!c)
            continue;
        conn_name(c, name, sizeof name);
        bool want = g.cfg.connector[0] && strcasecmp(g.cfg.connector, "auto")
                        ? !strcmp(name, g.cfg.connector)
                        : c->connection == DRM_MODE_CONNECTED;
        if (want && c->count_modes)
            conn = c;
        else
            drmModeFreeConnector(c);
    }
    if (!conn) {
        logm("DRM : connecteur « %s » introuvable ou sans mode. Connecteurs :", g.cfg.connector);
        for (int i = 0; i < res->count_connectors; i++) {
            drmModeConnector *c = drmModeGetConnector(k.fd, res->connectors[i]);
            if (!c)
                continue;
            logm("   %s (%s)", conn_name(c, name, sizeof name),
                 c->connection == DRM_MODE_CONNECTED ? "connecté" : "déconnecté");
            drmModeFreeConnector(c);
        }
        return -1;
    }
    k.conn = conn->connector_id;
    conn_name(conn, name, sizeof name);

    if (!pick_mode(conn, &k.mode)) {
        logm("DRM : mode « %s » introuvable sur %s. Modes disponibles :", g.cfg.hdmi_mode, name);
        for (int i = 0; i < conn->count_modes; i++)
            logm("   %2d : %dx%d%s@%u", i, conn->modes[i].hdisplay, conn->modes[i].vdisplay,
                 conn->modes[i].flags & DRM_MODE_FLAG_INTERLACE ? "i" : "",
                 conn->modes[i].vrefresh);
        return -1;
    }
    k.w = k.mode.hdisplay;
    k.h = k.mode.vdisplay;

    /* CRTC */
    k.crtc_idx = -1;
    for (int e = 0; e < conn->count_encoders && k.crtc_idx < 0; e++) {
        drmModeEncoder *enc = drmModeGetEncoder(k.fd, conn->encoders[e]);
        if (!enc)
            continue;
        for (int i = 0; i < res->count_crtcs; i++)
            if (enc->possible_crtcs & (1u << i)) {
                k.crtc_idx = i;
                k.crtc = res->crtcs[i];
                break;
            }
        drmModeFreeEncoder(enc);
    }
    drmModeFreeConnector(conn);
    drmModeFreeResources(res);
    if (k.crtc_idx < 0) {
        logm("DRM : pas de CRTC pour %s", name);
        return -1;
    }

    /* plans */
    drmModePlaneRes *pr = drmModeGetPlaneResources(k.fd);
    if (!pr)
        return -1;
    for (uint32_t i = 0; i < pr->count_planes && k.npl < MAX_PLANES; i++) {
        drmModePlane *p = drmModeGetPlane(k.fd, pr->planes[i]);
        if (!p)
            continue;
        if (p->possible_crtcs & (1u << k.crtc_idx)) {
            struct plane_info *pi = &k.pl[k.npl++];
            memset(pi, 0, sizeof *pi);
            pi->id = p->plane_id;
            for (uint32_t f = 0; f < p->count_formats; f++) {
                if (p->formats[f] == DRM_FORMAT_NV12) pi->nv12 = true;
                if (p->formats[f] == DRM_FORMAT_ARGB8888) pi->argb = true;
            }
            load_plane(pi);
        }
        drmModeFreePlane(p);
    }
    drmModeFreePlaneResources(pr);

    k.conn_crtc_prop = obj_prop(k.conn, DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID");
    k.crtc_mode_prop = obj_prop(k.crtc, DRM_MODE_OBJECT_CRTC, "MODE_ID");
    k.crtc_active_prop = obj_prop(k.crtc, DRM_MODE_OBJECT_CRTC, "ACTIVE");
    if (drmModeCreatePropertyBlob(k.fd, &k.mode, sizeof k.mode, &k.mode_blob)) {
        logm("DRM : création du blob de mode impossible");
        return -1;
    }

    /* plan OSD provisoire : premier overlay ARGB */
    for (int i = 0; i < k.npl && k.op < 0; i++)
        if (k.pl[i].type == 0 && k.pl[i].argb)
            k.op = i;
    if (k.op < 0)
        for (int i = 0; i < k.npl && k.op < 0; i++)
            if (k.pl[i].argb)
                k.op = i;
    if (k.op < 0) {
        logm("DRM : aucun plan ARGB8888 disponible");
        return -1;
    }

    for (int i = 0; i < 2; i++)
        if (dumb_create(&k.ov[i]) < 0) {
            logm("DRM : création du tampon OSD impossible : %s", strerror(errno));
            return -1;
        }
    k.surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, k.w, k.h);

    /* modeset initial : écran noir + OSD, tous les autres plans coupés */
    drmModeAtomicReq *r = drmModeAtomicAlloc();
    add(r, k.conn, k.conn_crtc_prop, k.crtc);
    add(r, k.crtc, k.crtc_mode_prop, k.mode_blob);
    add(r, k.crtc, k.crtc_active_prop, 1);
    for (int i = 0; i < k.npl; i++)
        if (i != k.op)
            plane_disable(r, &k.pl[i]);
    set_osd(r, k.op, k.ov[0].fb);
    int ret = drmModeAtomicCommit(k.fd, r, DRM_MODE_ATOMIC_ALLOW_MODESET, NULL);
    drmModeAtomicFree(r);
    if (ret) {
        logm("DRM : modeset impossible : %s%s", strerror(errno),
             errno == EACCES ? " (un autre programme utilise l'écran ? mpv ?)" : "");
        return -1;
    }
    k.ov_cur = 0;
    snprintf(g.output_desc, sizeof g.output_desc, "%s %dx%d@%u", name, k.w, k.h, k.mode.vrefresh);
    logm("DRM : %s, %d plans utilisables, OSD sur le plan %u", g.output_desc, k.npl,
         k.pl[k.op].id);
    return 0;
}

static void kms_close(void)
{
    if (k.fd < 0)
        return;
    for (int i = 0; i < 2; i++)
        dumb_destroy(&k.ov[i]);
    if (k.surf)
        cairo_surface_destroy(k.surf);
    if (k.mode_blob)
        drmModeDestroyPropertyBlob(k.fd, k.mode_blob);
    close(k.fd);
    k.fd = -1;
}

/* crée un framebuffer DRM à partir d'une image DRM PRIME (zéro copie) */
static int fb_from_frame(const AVFrame *f, uint32_t *fb)
{
    const AVDRMFrameDescriptor *d = (const AVDRMFrameDescriptor *)f->data[0];
    uint32_t bo[AV_DRM_MAX_PLANES] = { 0 };
    uint32_t handles[4] = { 0 }, pitches[4] = { 0 }, offsets[4] = { 0 };
    uint64_t mods[4] = { 0 };
    static bool logged;
    int ret = -1;

    if (!d || d->nb_layers < 1)
        return -1;
    for (int i = 0; i < d->nb_objects; i++)
        if (drmPrimeFDToHandle(k.fd, d->objects[i].fd, &bo[i])) {
            logm("DRM : import dmabuf impossible : %s", strerror(errno));
            goto out;
        }
    const AVDRMLayerDescriptor *L = &d->layers[0];
    if (d->nb_layers != 1 || L->nb_planes > 4) {
        logm("DRM : descripteur inattendu (%d couches)", d->nb_layers);
        goto out;
    }
    for (int p = 0; p < L->nb_planes; p++) {
        int o = L->planes[p].object_index;
        handles[p] = bo[o];
        pitches[p] = L->planes[p].pitch;
        offsets[p] = L->planes[p].offset;
        mods[p] = d->objects[o].format_modifier;
    }
    bool usemod = mods[0] != DRM_FORMAT_MOD_INVALID;
    if (!logged) {
        logged = true;
        logm("DRM : images %dx%d format %.4s modificateur 0x%016llx", f->width, f->height,
             (const char *)&L->format, (unsigned long long)mods[0]);
    }
    if (drmModeAddFB2WithModifiers(k.fd, f->width, f->height, L->format, handles, pitches,
                                   offsets, usemod ? mods : NULL, fb,
                                   usemod ? DRM_MODE_FB_MODIFIERS : 0)) {
        logm("DRM : AddFB2 refusé : %s", strerror(errno));
        goto out;
    }
    ret = 0;
out:
    /* le framebuffer garde sa propre référence : on peut fermer les handles GEM */
    for (int i = 0; i < d->nb_objects; i++) {
        if (!bo[i])
            continue;
        bool dup = false;
        for (int j = 0; j < i; j++)
            dup |= bo[j] == bo[i];
        if (!dup) {
            struct drm_gem_close gc = { .handle = bo[i] };
            drmIoctl(k.fd, DRM_IOCTL_GEM_CLOSE, &gc);
        }
    }
    return ret;
}

static bool vplane_allowed(int i)
{
    const char *v = g.cfg.video_plane;
    if (!k.pl[i].nv12)
        return false;
    if (!strcasecmp(v, "primary"))
        return k.pl[i].type == 1;
    if (!strcasecmp(v, "overlay"))
        return k.pl[i].type == 0;
    if (isdigit((unsigned char)v[0]))
        return k.pl[i].id == (uint32_t)atoi(v);
    return k.pl[i].type != 2;
}

/* au premier affichage : cherche (TEST_ONLY) une paire de plans vidéo/OSD acceptée */
static int kms_pick_planes(uint32_t fb, const AVFrame *f)
{
    int order[MAX_PLANES], n = 0;
    for (int pass = 0; pass < 2; pass++)          /* primaire d'abord, puis overlays */
        for (int i = 0; i < k.npl; i++)
            if (vplane_allowed(i) && ((pass == 0) == (k.pl[i].type == 1)))
                order[n++] = i;
    for (int a = 0; a < n; a++) {
        int vp = order[a];
        int ocand[MAX_PLANES], no = 0;
        if (k.op != vp)
            ocand[no++] = k.op;
        for (int i = 0; i < k.npl; i++)
            if (i != vp && i != k.op && k.pl[i].argb && k.pl[i].type != 2)
                ocand[no++] = i;
        for (int b = 0; b < no; b++) {
            int op = ocand[b];
            drmModeAtomicReq *r = drmModeAtomicAlloc();
            set_video(r, vp, fb, f);
            set_osd(r, op, k.ov[k.ov_cur].fb);
            if (op != k.op)
                plane_disable(r, &k.pl[k.op]);
            int ret = drmModeAtomicCommit(k.fd, r, DRM_MODE_ATOMIC_TEST_ONLY, NULL);
            int err = errno;
            drmModeAtomicFree(r);
            logm("DRM : essai vidéo=plan %u (%s) + OSD=plan %u : %s", k.pl[vp].id,
                 k.pl[vp].type == 1 ? "primary" : "overlay", k.pl[op].id,
                 ret ? strerror(err) : "OK");
            if (!ret) {
                if (op != k.op) {
                    k.disable_pending = k.op;
                    k.op = op;
                    k.osd_force = true;
                }
                k.vp = vp;
                k.video_ok = true;
                return 0;
            }
        }
    }
    logm("DRM : aucun plan n'accepte ces images (voir video_plane dans la config)");
    return -1;
}

/* ------------------------------------------------------------------ */
/* OSD : tally + UMD + NO SIGNAL (cairo, uniquement sur changement)    */
/* ------------------------------------------------------------------ */

struct osd_state {
    int sel;
    tally_t tally;
    bool nosig;
    char label[LABEL_MAX];
};

static bool osd_differs(const struct osd_state *a, const struct osd_state *b)
{
    return a->sel != b->sel || a->tally != b->tally || a->nosig != b->nosig ||
           strcmp(a->label, b->label);
}

static void text_centered(cairo_t *cr, const char *txt, double size, double maxw, double cx,
                          double cy)
{
    cairo_text_extents_t te;
    cairo_select_font_face(cr, g.cfg.font, CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
    cairo_set_font_size(cr, size);
    cairo_text_extents(cr, txt, &te);
    if (te.x_advance > maxw && te.x_advance > 0) {
        cairo_set_font_size(cr, size * maxw / te.x_advance);
        cairo_text_extents(cr, txt, &te);
    }
    cairo_move_to(cr, cx - (te.x_bearing + te.width / 2), cy - (te.y_bearing + te.height / 2));
    cairo_show_text(cr, txt);
}

static void osd_render(int buf, const struct osd_state *o)
{
    const double W = k.w, H = k.h, s = H / 1080.0;
    cairo_t *cr = cairo_create(k.surf);
    cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
    cairo_paint(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);

    double r = 0, gg = 0, b = 0;
    if (o->tally == TALLY_PGM) { r = 0xE0 / 255.0; gg = 0; b = 0; }
    if (o->tally == TALLY_PVW) { r = 0; gg = 0xB0 / 255.0; b = 0; }

    const double bw = round(14 * s);
    if (o->tally != TALLY_OFF) {
        cairo_set_source_rgb(cr, r, gg, b);
        cairo_rectangle(cr, 0, 0, W, bw);
        cairo_rectangle(cr, 0, H - bw, W, bw);
        cairo_rectangle(cr, 0, bw, bw, H - 2 * bw);
        cairo_rectangle(cr, W - bw, bw, bw, H - 2 * bw);
        cairo_fill(cr);
    }

    /* bandeau UMD 600x70, centré en bas, 24 px au-dessus de la bordure */
    const double uw = round(600 * s), uh = round(70 * s);
    const double ux = round((W - uw) / 2), uy = round(H - bw - 24 * s - uh);
    if (o->tally == TALLY_OFF)
        cairo_set_source_rgba(cr, 0, 0, 0, g.cfg.umd_off_alpha);
    else
        cairo_set_source_rgb(cr, r, gg, b);
    cairo_rectangle(cr, ux, uy, uw, uh);
    cairo_fill(cr);
    if (o->label[0]) {
        cairo_set_source_rgb(cr, 1, 1, 1);
        text_centered(cr, o->label, 46 * s, uw - 20 * s, ux + uw / 2, uy + uh / 2);
    }

    if (o->nosig) {
        const double nw = round(560 * s), nh = round(130 * s);
        cairo_set_source_rgba(cr, 0, 0, 0, 0.65);
        cairo_rectangle(cr, round((W - nw) / 2), round((H - nh) / 2), nw, nh);
        cairo_fill(cr);
        cairo_set_source_rgb(cr, 1, 1, 1);
        text_centered(cr, "NO SIGNAL", 80 * s, nw - 40 * s, W / 2, H / 2);
    }
    cairo_destroy(cr);
    cairo_surface_flush(k.surf);

    const uint8_t *src = cairo_image_surface_get_data(k.surf);
    const int sstride = cairo_image_surface_get_stride(k.surf);
    struct dumb *d = &k.ov[buf];
    for (int y = 0; y < k.h; y++)
        memcpy(d->map + (size_t)y * d->pitch, src + (size_t)y * sstride, (size_t)k.w * 4);
}

/* ------------------------------------------------------------------ */
/* Thread d'affichage                                                  */
/* ------------------------------------------------------------------ */

static void *display_thread(void *arg)
{
    (void)arg;
    pthread_setname_np(pthread_self(), "display");
    set_rt();

    AVFrame *cur = NULL;
    uint32_t cur_fb = 0;
    int shown_cam = -1;
    uint64_t shown_seq = 0;
    struct osd_state drawn;
    bool drawn_valid = false;
    int64_t last_err_log = 0;

    memset(&drawn, 0, sizeof drawn);
    pthread_mutex_lock(&g.lock);
    while (!g.quit) {
        const int sel = g.selected;
        struct cam *c = &g.cam[sel];
        const int64_t t = now_us();
        struct osd_state want;
        memset(&want, 0, sizeof want);
        want.sel = sel;
        want.tally = c->tally;
        snprintf(want.label, sizeof want.label, "%s", c->label);
        want.nosig = !(c->state == ST_STREAMING &&
                       t - c->last_frame_us < (int64_t)g.cfg.stall_timeout_ms * 1000);

        bool osd_dirty = !drawn_valid || osd_differs(&want, &drawn) || k.osd_force;
        bool new_frame = c->latest && c->seq && (sel != shown_cam || c->seq != shown_seq);
        bool blank = !c->latest && sel != shown_cam;

        if (!osd_dirty && !new_frame && !blank) {
            struct timespec ts;
            clock_gettime(CLOCK_MONOTONIC, &ts);
            ts.tv_nsec += 100 * 1000000;
            if (ts.tv_nsec >= 1000000000) {
                ts.tv_sec++;
                ts.tv_nsec -= 1000000000;
            }
            pthread_cond_timedwait(&g.cond, &g.lock, &ts);
            continue;
        }

        AVFrame *nf = NULL;
        uint64_t nseq = 0;
        if (new_frame) {
            nf = av_frame_clone(c->latest);
            nseq = c->seq;
        }
        const int64_t sw_req = sel != shown_cam ? g.switch_req_us : 0;
        const double age_ms = nf ? (t - c->last_frame_us) / 1000.0 : 0;
        pthread_mutex_unlock(&g.lock);

        uint32_t nfb = 0;
        if (nf && fb_from_frame(nf, &nfb) < 0) {
            av_frame_free(&nf);
            shown_seq = nseq;          /* on attend l'image suivante */
            usleep(20000);
        }
        if (nf && !k.video_ok && kms_pick_planes(nfb, nf) < 0) {
            drmModeRmFB(k.fd, nfb);
            av_frame_free(&nf);
            shown_seq = nseq;
            sleep_ms(1000);
            pthread_mutex_lock(&g.lock);
            continue;
        }
        osd_dirty |= k.osd_force;
        int ob = -1;
        if (osd_dirty) {
            ob = k.ov_cur ^ 1;
            osd_render(ob, &want);
        }

        drmModeAtomicReq *req = drmModeAtomicAlloc();
        if (nf)
            set_video(req, k.vp, nfb, nf);
        else if (blank && k.vp >= 0)
            plane_disable(req, &k.pl[k.vp]);
        if (k.disable_pending >= 0)
            plane_disable(req, &k.pl[k.disable_pending]);
        if (ob >= 0)
            set_osd(req, k.op, k.ov[ob].fb);
        int ret = drmModeAtomicCommit(k.fd, req, 0, NULL);   /* bloquant : rend la main après le vblank */
        int err = errno;
        drmModeAtomicFree(req);

        if (ret) {
            if (now_us() - last_err_log > 5000000) {
                logm("DRM : commit refusé : %s", strerror(err));
                last_err_log = now_us();
            }
            if (nf) {
                drmModeRmFB(k.fd, nfb);
                av_frame_free(&nf);
                shown_seq = nseq;
            }
            usleep(20000);
            pthread_mutex_lock(&g.lock);
            continue;
        }

        k.disable_pending = -1;
        if (ob >= 0) {
            k.ov_cur = ob;
            drawn = want;
            drawn_valid = true;
            k.osd_force = false;
        }
        double sw_ms = -1;
        if (nf || blank) {
            if (cur) {
                drmModeRmFB(k.fd, cur_fb);
                av_frame_free(&cur);
            }
            cur = nf;
            cur_fb = nfb;
            if (sel != shown_cam) {
                if (shown_cam < 0)
                    logm("affichage : première image (cam%d)", sel + 1);
                else if (sw_req) {
                    sw_ms = (now_us() - sw_req) / 1000.0;
                    logm("bascule cam%d -> cam%d : %.1f ms après la requête%s", shown_cam + 1,
                         sel + 1, sw_ms, blank ? " (pas d'image : écran noir)" : "");
                    (void)age_ms;
                }
            }
            shown_cam = sel;
            shown_seq = nf ? nseq : 0;
        }
        pthread_mutex_lock(&g.lock);
        if (sw_ms >= 0)
            g.last_switch_ms = sw_ms;
    }
    pthread_mutex_unlock(&g.lock);

    if (cur) {
        drmModeRmFB(k.fd, cur_fb);
        av_frame_free(&cur);
    }
    return NULL;
}

/* ------------------------------------------------------------------ */
/* API HTTP                                                            */
/* ------------------------------------------------------------------ */

static char *status_json(void)
{
    struct sbuf s = { 0 };
    int64_t t = now_us();
    pthread_mutex_lock(&g.lock);
    sb_printf(&s, "{\"ok\":true,\"active\":%d,\"output\":", g.selected + 1);
    sb_json_str(&s, g.no_display ? "none" : g.output_desc);
    sb_printf(&s, ",\"uptime_s\":%lld,\"last_switch_ms\":%.1f,\"cameras\":[",
              (long long)((t - g.start_us) / 1000000), g.last_switch_ms);
    for (int i = 0; i < NCAM; i++) {
        struct cam *c = &g.cam[i];
        bool sig = c->state == ST_STREAMING &&
                   t - c->last_frame_us < (int64_t)g.cfg.stall_timeout_ms * 1000;
        sb_printf(&s, "%s{\"cam\":%d,\"label\":", i ? "," : "", i + 1);
        sb_json_str(&s, c->label);
        sb_printf(&s, ",\"tally\":\"%s\",\"state\":\"%s\",\"connected\":%s,\"signal\":%s,"
                      "\"fps\":%.1f,\"mbps\":%.2f,\"width\":%d,\"height\":%d,"
                      "\"connects\":%u,\"decode_errors\":%u,\"last_error\":",
                  tally_name[c->tally], state_name[c->state],
                  c->state == ST_CONNECTED || c->state == ST_STREAMING ? "true" : "false",
                  sig ? "true" : "false", sig ? c->fps : 0.0, sig ? c->mbps : 0.0, c->width,
                  c->height, c->connects, c->decode_errors);
        sb_json_str(&s, c->last_error);
        sb_printf(&s, "}");
    }
    pthread_mutex_unlock(&g.lock);
    sb_printf(&s, "],\"system\":{\"mem_available_kb\":%ld,\"swap_free_kb\":%ld,"
                  "\"cma_total_kb\":%ld,\"cma_free_kb\":%ld,\"temp_c\":%.1f}}\n",
              meminfo_kb("MemAvailable"), meminfo_kb("SwapFree"), meminfo_kb("CmaTotal"),
              meminfo_kb("CmaFree"), soc_temp());
    return s.b;
}

static char *error_json(const char *msg)
{
    struct sbuf s = { 0 };
    sb_printf(&s, "{\"ok\":false,\"error\":");
    sb_json_str(&s, msg);
    sb_printf(&s, "}\n");
    return s.b;
}

static enum MHD_Result reply(struct MHD_Connection *conn, unsigned code, char *body)
{
    struct MHD_Response *r =
        MHD_create_response_from_buffer_with_free_callback(strlen(body), body, free);
    MHD_add_response_header(r, "Content-Type", "application/json; charset=utf-8");
    MHD_add_response_header(r, "Access-Control-Allow-Origin", "*");
    enum MHD_Result ret = MHD_queue_response(conn, code, r);
    MHD_destroy_response(r);
    return ret;
}

struct req { char body[512]; size_t len; };

static void url_decode_form(char *s)
{
    for (char *p = s; *p; p++)
        if (*p == '+')
            *p = ' ';
    MHD_http_unescape(s);
}

static enum MHD_Result http_cb(void *cls, struct MHD_Connection *conn, const char *url,
                               const char *method, const char *version,
                               const char *upload, size_t *upload_size, void **con_cls)
{
    (void)cls;
    (void)version;
    struct req *rq = *con_cls;
    if (!rq) {
        rq = calloc(1, sizeof *rq);
        if (!rq)
            return MHD_NO;
        *con_cls = rq;
        return MHD_YES;
    }
    if (*upload_size) {
        size_t n = *upload_size;
        if (n > sizeof rq->body - 1 - rq->len)
            n = sizeof rq->body - 1 - rq->len;
        memcpy(rq->body + rq->len, upload, n);
        rq->len += n;
        rq->body[rq->len] = 0;
        *upload_size = 0;
        return MHD_YES;
    }
    if (strcmp(method, "GET") && strcmp(method, "POST") && strcmp(method, "PUT"))
        return reply(conn, 405, error_json("méthode non supportée"));

    int n = 0, len = 0;
    char word[16];

    if (!strcmp(url, "/") || !strcmp(url, "/status"))
        return reply(conn, 200, status_json());

    if (sscanf(url, "/select/%d%n", &n, &len) == 1 && !url[len]) {
        if (n < 1 || n > NCAM)
            return reply(conn, 400, error_json("caméra 1 à 4"));
        pthread_mutex_lock(&g.lock);
        if (g.selected != n - 1) {
            g.selected = n - 1;
            g.switch_req_us = now_us();
            pthread_cond_broadcast(&g.cond);
        }
        pthread_mutex_unlock(&g.lock);
        return reply(conn, 200, status_json());
    }

    if (sscanf(url, "/tally/%d/%15[a-zA-Z]%n", &n, word, &len) == 2 && !url[len]) {
        int t = parse_tally(word);
        if (n < 1 || n > NCAM || t < 0)
            return reply(conn, 400, error_json("usage : /tally/<1-4>/<off|pvw|pgm>"));
        pthread_mutex_lock(&g.lock);
        g.cam[n - 1].tally = t;
        pthread_cond_broadcast(&g.cond);
        pthread_mutex_unlock(&g.lock);
        return reply(conn, 200, status_json());
    }

    if (sscanf(url, "/label/%d%n", &n, &len) == 1 && !url[len]) {
        if (n < 1 || n > NCAM)
            return reply(conn, 400, error_json("caméra 1 à 4"));
        char txt[512];
        const char *q = MHD_lookup_connection_value(conn, MHD_GET_ARGUMENT_KIND, "text");
        if (q)
            snprintf(txt, sizeof txt, "%s", q);
        else if (rq->len) {
            snprintf(txt, sizeof txt, "%s", !strncmp(rq->body, "text=", 5) ? rq->body + 5 : rq->body);
            if (!strncmp(rq->body, "text=", 5))
                url_decode_form(txt);
        } else
            return reply(conn, 400, error_json("texte manquant (?text=... ou corps de requête)"));
        pthread_mutex_lock(&g.lock);
        clean_label(g.cam[n - 1].label, txt);
        pthread_cond_broadcast(&g.cond);
        pthread_mutex_unlock(&g.lock);
        return reply(conn, 200, status_json());
    }

    return reply(conn, 404, error_json("routes : /status /select/N /tally/N/off|pvw|pgm /label/N"));
}

static void http_done(void *cls, struct MHD_Connection *c, void **con_cls,
                      enum MHD_RequestTerminationCode toe)
{
    (void)cls;
    (void)c;
    (void)toe;
    free(*con_cls);
    *con_cls = NULL;
}

/* ------------------------------------------------------------------ */
/* main                                                                */
/* ------------------------------------------------------------------ */

static void on_signal(int sig)
{
    (void)sig;
    if (g.quit)
        _exit(1);              /* 2e Ctrl+C : sortie immédiate */
    g.quit = 1;
}

static int parse_loglevel(const char *s)
{
    static const struct { const char *n; int v; } t[] = {
        { "quiet", AV_LOG_QUIET }, { "error", AV_LOG_ERROR }, { "warning", AV_LOG_WARNING },
        { "info", AV_LOG_INFO }, { "verbose", AV_LOG_VERBOSE }, { "debug", AV_LOG_DEBUG },
    };
    for (size_t i = 0; i < sizeof t / sizeof *t; i++)
        if (!strcasecmp(s, t[i].n))
            return t[i].v;
    return AV_LOG_ERROR;
}

int main(int argc, char **argv)
{
    const char *cfgpath = "ptzview.conf";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-n"))
            g.no_display = true;
        else if (!strcmp(argv[i], "-h") || !strcmp(argv[i], "--help")) {
            fprintf(stderr, "usage : %s [-n] [fichier.conf]\n  -n : sans affichage\n", argv[0]);
            return 0;
        } else
            cfgpath = argv[i];
    }

    config_defaults();
    if (load_config(cfgpath) < 0)
        return 1;
    g.selected = g.cfg.start_camera - 1;
    g.start_us = now_us();

    pthread_condattr_t ca;
    pthread_condattr_init(&ca);
    pthread_condattr_setclock(&ca, CLOCK_MONOTONIC);
    pthread_cond_init(&g.cond, &ca);
    pthread_mutex_init(&g.lock, NULL);

    struct sigaction sa = { .sa_handler = on_signal };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    av_log_set_level(parse_loglevel(g.cfg.loglevel));
    avformat_network_init();

    enum AVHWDeviceType ht = av_hwdevice_find_type_by_name(g.cfg.hwaccel);
    int r = ht == AV_HWDEVICE_TYPE_NONE ? AVERROR(ENOSYS)
                                        : av_hwdevice_ctx_create(&g.hwdev, ht,
                                                                 g.cfg.hwaccel_device[0] ? g.cfg.hwaccel_device : NULL,
                                                                 NULL, 0);
    if (r < 0) {
        char e[96];
        av_strerror(r, e, sizeof e);
        logm("hwaccel « %s » indisponible : %s (ffmpeg -hwaccels pour la liste)", g.cfg.hwaccel, e);
        if (!g.no_display)
            return 1;
        logm("mode -n : on continue sans décodage matériel (aucune image ne sera produite)");
    }

    if (!g.no_display && kms_init() < 0) {
        kms_close();
        return 1;
    }

    struct MHD_Daemon *httpd = MHD_start_daemon(
        MHD_USE_INTERNAL_POLLING_THREAD | MHD_USE_ERROR_LOG, (uint16_t)g.cfg.http_port, NULL, NULL,
        http_cb, NULL, MHD_OPTION_NOTIFY_COMPLETED, http_done, NULL,
        MHD_OPTION_CONNECTION_TIMEOUT, (unsigned)10, MHD_OPTION_END);
    if (!httpd)
        logm("HTTP : impossible d'écouter sur le port %d", g.cfg.http_port);
    else
        logm("HTTP : API sur le port %d", g.cfg.http_port);

    pthread_t disp;
    if (!g.no_display)
        pthread_create(&disp, NULL, display_thread, NULL);
    for (int i = 0; i < NCAM; i++)
        pthread_create(&g.cam[i].th, NULL, cam_thread, &g.cam[i]);

    logm("prêt : cam%d à l'écran, latence SRT %d ms. Ctrl+C pour quitter.", g.selected + 1,
         g.cfg.srt_latency_ms);

    int64_t next_stats = now_us() + (int64_t)g.cfg.stats_interval_s * 1000000;
    while (!g.quit) {
        usleep(100000);
        if (g.cfg.stats_interval_s > 0 && now_us() >= next_stats) {
            next_stats += (int64_t)g.cfg.stats_interval_s * 1000000;
            char line[512];
            int n = 0;
            int64_t t = now_us();
            pthread_mutex_lock(&g.lock);
            for (int i = 0; i < NCAM; i++) {
                struct cam *c = &g.cam[i];
                bool sig = c->state == ST_STREAMING &&
                           t - c->last_frame_us < (int64_t)g.cfg.stall_timeout_ms * 1000;
                n += snprintf(line + n, sizeof line - n, "%scam%d%s %s ", i ? "| " : "", i + 1,
                              i == g.selected ? "*" : "", tally_name[c->tally]);
                if (sig)
                    n += snprintf(line + n, sizeof line - n, "%.1f i/s %.1f Mb/s ", c->fps, c->mbps);
                else
                    n += snprintf(line + n, sizeof line - n, "%s ", state_name[c->state]);
            }
            pthread_mutex_unlock(&g.lock);
            logm("%s| CMA libre %ld Mo | RAM dispo %ld Mo | %.1f °C", line,
                 meminfo_kb("CmaFree") / 1024, meminfo_kb("MemAvailable") / 1024, soc_temp());
        }
    }

    logm("arrêt en cours...");
    pthread_mutex_lock(&g.lock);
    pthread_cond_broadcast(&g.cond);
    pthread_mutex_unlock(&g.lock);
    if (!g.no_display)
        pthread_join(disp, NULL);
    for (int i = 0; i < NCAM; i++)
        pthread_join(g.cam[i].th, NULL);
    if (httpd)
        MHD_stop_daemon(httpd);
    for (int i = 0; i < NCAM; i++)
        av_frame_free(&g.cam[i].latest);
    av_buffer_unref(&g.hwdev);
    kms_close();
    avformat_network_deinit();
    logm("terminé.");
    return 0;
}
