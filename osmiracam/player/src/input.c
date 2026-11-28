/* input.c — one thread per input: SRT reception + hardware HEVC decoding. */
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "ptzview.h"

/* ------------------------------------------------------------------ */
/* Entrées : réception SRT + décodage HEVC matériel                    */
/* ------------------------------------------------------------------ */

static int interrupt_cb(void *opaque)
{
    struct cam *c = opaque;
    if (g.quit || c->reload)
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

/* Sleep up to ms, waking up early to quit or to apply a new URL. */
static void cam_wait(struct cam *c, int ms)
{
    int64_t end = now_us() + (int64_t)ms * 1000;
    while (!g.quit && !c->reload && now_us() < end)
        usleep(20000);
}

void *cam_thread(void *arg)
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
        if (!first && !c->reload) {
            cam_set_state(c, ST_WAITING);
            cam_wait(c, g.cfg.reconnect_ms);
            if (g.quit)
                break;
        }
        first = false;

        /* Take the URL (it can change at any time through POST /input/N). */
        char url[sizeof c->url];
        pthread_mutex_lock(&g.lock);
        snprintf(url, sizeof url, "%s", c->url);
        int latency_ms = c->latency_ms >= 0 ? c->latency_ms : g.cfg.srt_latency_ms;
        c->reload = 0;
        pthread_mutex_unlock(&g.lock);
        if (!url[0]) {
            /* No URL: input disabled, no connection attempt until one is given. */
            cam_set_state(c, ST_DISABLED);
            while (!g.quit && !c->reload)
                usleep(50000);
            continue;
        }
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
        av_dict_set_int(&opt, "latency", (int64_t)latency_ms * 1000, 0);
        av_dict_set_int(&opt, "connect_timeout", g.cfg.connect_timeout_ms, 0);
        av_dict_set(&opt, "transtype", "live", 0);

        c->deadline_us = now_us() + (int64_t)(g.cfg.connect_timeout_ms + 2000) * 1000;
        srt_hooks_opening(c);
        r = avformat_open_input(&fmt, url, ts, &opt);
        srt_hooks_opening(NULL);
        av_dict_free(&opt);
        if (r < 0) {
            forget_srt_sock(c);
            if (!c->reload)
                cam_error(c, "connexion", r);
            continue;
        }
        pthread_mutex_lock(&g.lock);
        c->state = ST_CONNECTED;
        c->connects++;
        pthread_cond_broadcast(&g.cond);
        pthread_mutex_unlock(&g.lock);
        logm("cam%d : connecté (%s, latence %d ms)", c->idx + 1, url, latency_ms);
        c->prev_err[0] = 0;

        int64_t win_start = now_us();
        unsigned win_frames = 0;
        uint64_t win_bytes = 0;

        while (!g.quit) {
            c->deadline_us = now_us() + (int64_t)g.cfg.stall_timeout_ms * 1000;
            r = av_read_frame(fmt, pkt);
            if (r < 0) {
                if (!c->reload)
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
        forget_srt_sock(c);
        avformat_close_input(&fmt);
        if (c->reload)
            logm("cam%d : nouveaux réglages, reconnexion", c->idx + 1);
        else if (!g.quit)
            logm("cam%d : déconnecté, nouvel essai dans %d ms", c->idx + 1, g.cfg.reconnect_ms);
    }
    av_packet_free(&pkt);
    av_frame_free(&frm);
    return NULL;
}
