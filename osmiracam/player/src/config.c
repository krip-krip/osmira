/* config.c — default values and ptzview.conf parsing. */
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "ptzview.h"

const char *const tally_name[] = { "off", "pvw", "pgm" };
const char *const state_name[] = { "connecting", "connected", "streaming", "waiting", "disabled" };

/* ------------------------------------------------------------------ */
/* Configuration                                                       */
/* ------------------------------------------------------------------ */

void config_defaults(void)
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
    c->cameras = 4;
    c->start_camera = 1;
    strcpy(c->font, "DejaVu Sans");
    c->umd_off_alpha = 0.30;
    c->stats_interval_s = 10;
    c->rt_priority = 0;
    strcpy(c->loglevel, "error");
    for (int i = 0; i < MAX_CAMS; i++) {
        struct cam *cm = &g.cam[i];
        cm->idx = i;
        snprintf(cm->url, sizeof cm->url,
                 "srt://192.168.104.253:8890?mode=caller&streamid=read:cam%d", i + 1);
        snprintf(cm->label, sizeof cm->label, "CAM %d", i + 1);
        cm->tally = TALLY_OFF;
        cm->latency_ms = -1;
        cm->srt_sock = SRT_INVALID_SOCK;
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

int parse_tally(const char *s)
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
    CFG_INT(cameras) CFG_INT(http_port) CFG_INT(start_camera) CFG_STR(font)
    CFG_DBL(umd_off_alpha) CFG_INT(stats_interval_s) CFG_INT(rt_priority) CFG_STR(loglevel)
    return -1;
}

/* N of a [camN] section (1..MAX_CAMS), 0 if the section is not one. */
static int cam_section(const char *sect)
{
    char *end;
    if (strncmp(sect, "cam", 3) || !isdigit((unsigned char)sect[3]))
        return 0;
    long n = strtol(sect + 3, &end, 10);
    return !*end && n >= 1 && n <= MAX_CAMS ? (int)n : 0;
}

int load_config(const char *path)
{
    FILE *f = fopen(path, "r");
    char line[1024], sect[32] = "";
    int ln = 0, last_cam = 0;
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
        } else if (cam_section(sect)) {
            int n = cam_section(sect);
            struct cam *c = &g.cam[n - 1];
            if (n > last_cam)
                last_cam = n;
            if (!strcmp(k, "url"))
                snprintf(c->url, sizeof c->url, "%s", v);
            else if (!strcmp(k, "latency_ms"))
                c->latency_ms = *v ? atoi(v) : -1;
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
    if (g.cfg.cameras < 1 || g.cfg.cameras > MAX_CAMS) {
        int n = g.cfg.cameras < 1 ? 1 : MAX_CAMS;
        logm("config : cameras = %d hors limites (1 à %d) : %d entrées", g.cfg.cameras, MAX_CAMS,
             n);
        g.cfg.cameras = n;
    }
    if (last_cam > g.cfg.cameras)
        logm("config : sections [cam%d] à [cam%d] ignorées (cameras = %d)", g.cfg.cameras + 1,
             last_cam, g.cfg.cameras);
    if (g.cfg.start_camera < 1 || g.cfg.start_camera > g.cfg.cameras)
        g.cfg.start_camera = 1;
    return 0;
}
