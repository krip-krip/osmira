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
#include <stdio.h>
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

    http_start(g.cfg.http_port);

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
    http_stop();
    for (int i = 0; i < NCAM; i++)
        av_frame_free(&g.cam[i].latest);
    av_buffer_unref(&g.hwdev);
    kms_close();
    avformat_network_deinit();
    logm("terminé.");
    return 0;
}
