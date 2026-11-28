/*
 * ptzview — lecteur N x SRT/HEVC (Raspberry Pi 4 et autres)
 *
 *  - N entrées SRT (MPEG-TS/HEVC, réglage cameras, 4 par défaut) reçues et
 *    décodées en permanence
 *    (FFmpeg "+rpt", hwaccel drm -> images DRM PRIME, zéro copie)
 *  - affichage DRM/KMS atomique : la caméra choisie sur un plan vidéo,
 *    tally + UMD + NO SIGNAL sur un plan ARGB au-dessus (redessiné
 *    seulement quand l'état change)
 *  - API HTTP (libmicrohttpd) : sélection, texte, tally, état JSON
 *
 * Usage : ptzview [-n] [fichier.conf]
 *   -n : pas d'affichage (décodage + API seulement, pour diagnostic)
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

#include "ptzview.h"

struct state g;

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
    for (int i = 0; i < MAX_OUTPUTS; i++)
        g.out[i].selected = g.cfg.out[i].start_camera - 1;
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

    http_start(g.cfg.http_port);

    for (int i = 0; i < g.cfg.outputs; i++)
        if (g.out[i].connected)
            pthread_create(&g.out[i].th, NULL, display_thread, (void *)(intptr_t)i);
    for (int i = 0; i < g.cfg.cameras; i++)
        pthread_create(&g.cam[i].th, NULL, cam_thread, &g.cam[i]);

    for (int i = 0; i < g.cfg.outputs; i++)
        logm("%s%s, cam%d", out_tag(i), g.out[i].connected ? g.out[i].desc : "pas d'écran",
             g.out[i].selected + 1);
    logm("prêt : %d entrées, %d sortie(s), latence SRT %d ms. Ctrl+C pour quitter.",
         g.cfg.cameras, g.cfg.outputs, g.cfg.srt_latency_ms);

    int64_t next_stats = now_us() + (int64_t)g.cfg.stats_interval_s * 1000000;
    while (!g.quit) {
        usleep(100000);
        if (g.cfg.stats_interval_s > 0 && now_us() >= next_stats) {
            next_stats += (int64_t)g.cfg.stats_interval_s * 1000000;
            struct sbuf line = { 0 };
            int64_t t = now_us();
            pthread_mutex_lock(&g.lock);
            for (int i = 0; i < g.cfg.cameras; i++) {
                struct cam *c = &g.cam[i];
                bool sig = c->state == ST_STREAMING &&
                           t - c->last_frame_us < (int64_t)g.cfg.stall_timeout_ms * 1000;
                /* "*": shown (single output), "*2": shown on output 2 */
                sb_printf(&line, "%scam%d", i ? "| " : "", i + 1);
                for (int o = 0; o < g.cfg.outputs; o++)
                    if (g.out[o].selected == i) {
                        if (g.cfg.outputs > 1)
                            sb_printf(&line, "*%d", o + 1);
                        else
                            sb_printf(&line, "*");
                    }
                sb_printf(&line, " %s ", tally_name[c->tally]);
                if (sig)
                    sb_printf(&line, "%.1f i/s %.1f Mb/s ", c->fps, c->mbps);
                else
                    sb_printf(&line, "%s ", state_name[c->state]);
            }
            pthread_mutex_unlock(&g.lock);
            logm("%s| CMA libre %ld Mo | RAM dispo %ld Mo | %.1f °C", line.b ? line.b : "",
                 meminfo_kb("CmaFree") / 1024, meminfo_kb("MemAvailable") / 1024, soc_temp());
            free(line.b);
        }
    }

    logm("arrêt en cours...");
    pthread_mutex_lock(&g.lock);
    pthread_cond_broadcast(&g.cond);
    pthread_mutex_unlock(&g.lock);
    for (int i = 0; i < g.cfg.outputs; i++)
        if (g.out[i].connected)
            pthread_join(g.out[i].th, NULL);
    for (int i = 0; i < g.cfg.cameras; i++)
        pthread_join(g.cam[i].th, NULL);
    http_stop();
    for (int i = 0; i < MAX_CAMS; i++)
        av_frame_free(&g.cam[i].latest);
    av_buffer_unref(&g.hwdev);
    kms_close();
    avformat_network_deinit();
    logm("terminé.");
    return 0;
}
