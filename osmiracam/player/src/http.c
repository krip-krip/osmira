/* http.c — local HTTP API (libmicrohttpd): /status, /select, /tally, /label, /input. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <microhttpd.h>

#include "ptzview.h"

/* ------------------------------------------------------------------ */
/* API HTTP                                                            */
/* ------------------------------------------------------------------ */

static char *status_json(void)
{
    struct sbuf s = { 0 };
    int64_t t = now_us();
    pthread_mutex_lock(&g.lock);
    /* active, output, last_switch_ms: output 1 (kept for older clients) */
    const struct output *o1 = &g.out[0];
    sb_printf(&s, "{\"ok\":true,\"inputs\":%d,\"active\":%d,\"output\":", g.cfg.cameras,
              o1->selected + 1);
    sb_json_str(&s, o1->connected ? o1->desc : "none");
    sb_printf(&s, ",\"uptime_s\":%lld,\"last_switch_ms\":%.1f,\"outputs\":[",
              (long long)((t - g.start_us) / 1000000), o1->last_switch_ms);
    for (int i = 0; i < g.cfg.outputs; i++) {
        const struct output *o = &g.out[i];
        sb_printf(&s, "%s{\"output\":%d,\"connected\":%s,\"screen\":", i ? "," : "", i + 1,
                  o->connected ? "true" : "false");
        if (o->connected)
            sb_json_str(&s, o->desc);
        else
            sb_printf(&s, "null");
        sb_printf(&s, ",\"active\":%d,\"last_switch_ms\":%.1f}", o->selected + 1,
                  o->last_switch_ms);
    }
    sb_printf(&s, "],\"cameras\":[");
    for (int i = 0; i < g.cfg.cameras; i++) {
        struct cam *c = &g.cam[i];
        bool sig = c->state == ST_STREAMING &&
                   t - c->last_frame_us < (int64_t)g.cfg.stall_timeout_ms * 1000;
        sb_printf(&s, "%s{\"cam\":%d,\"url\":", i ? "," : "", i + 1);
        sb_json_str(&s, c->url);
        sb_printf(&s, ",\"latency_ms\":%d",
                  c->latency_ms >= 0 ? c->latency_ms : g.cfg.srt_latency_ms);
        sb_printf(&s, ",\"label\":");
        sb_json_str(&s, c->label);
        sb_printf(&s, ",\"tally\":\"%s\",\"state\":\"%s\",\"connected\":%s,\"signal\":%s,"
                      "\"fps\":%.1f,\"mbps\":%.2f,\"width\":%d,\"height\":%d,"
                      "\"connects\":%u,\"decode_errors\":%u,\"last_error\":",
                  tally_name[c->tally], state_name[c->state],
                  c->state == ST_CONNECTED || c->state == ST_STREAMING ? "true" : "false",
                  sig ? "true" : "false", sig ? c->fps : 0.0, sig ? c->mbps : 0.0, c->width,
                  c->height, c->connects, c->decode_errors);
        sb_json_str(&s, c->last_error);
        sb_printf(&s, ",\"srt\":");
        srt_json(&s, c->srt_sock);
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

/* 400 answer for an input number outside 1..cameras. */
static char *range_error(void)
{
    char msg[64];
    snprintf(msg, sizeof msg, "caméra 1 à %d", g.cfg.cameras);
    return error_json(msg);
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

/* Value of a form field: query string first, then an url-encoded body. */
static bool form_value(struct MHD_Connection *conn, const struct req *rq, const char *key,
                       char *out, size_t size)
{
    const char *q = MHD_lookup_connection_value(conn, MHD_GET_ARGUMENT_KIND, key);
    if (q) {
        snprintf(out, size, "%s", q);
        return true;
    }
    size_t klen = strlen(key);
    for (const char *p = rq->body; *p;) {
        const char *end = strchr(p, '&');
        size_t flen = end ? (size_t)(end - p) : strlen(p);
        if (flen > klen && !strncmp(p, key, klen) && p[klen] == '=') {
            size_t vlen = flen - klen - 1;
            if (vlen >= size)
                vlen = size - 1;
            memcpy(out, p + klen + 1, vlen);
            out[vlen] = 0;
            url_decode_form(out);
            return true;
        }
        if (!end)
            break;
        p = end + 1;
    }
    return false;
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

    /* /select/N: output 1; /output/M/select/N: output M */
    int m = 1;
    if ((sscanf(url, "/select/%d%n", &n, &len) == 1 && !url[len]) ||
        (sscanf(url, "/output/%d/select/%d%n", &m, &n, &len) == 2 && !url[len])) {
        if (m < 1 || m > g.cfg.outputs) {
            char msg[64];
            snprintf(msg, sizeof msg, "sortie 1 à %d", g.cfg.outputs);
            return reply(conn, 400, error_json(msg));
        }
        if (n < 1 || n > g.cfg.cameras)
            return reply(conn, 400, range_error());
        struct output *o = &g.out[m - 1];
        pthread_mutex_lock(&g.lock);
        if (o->selected != n - 1) {
            o->selected = n - 1;
            o->switch_req_us = now_us();
            pthread_cond_broadcast(&g.cond);
        }
        pthread_mutex_unlock(&g.lock);
        return reply(conn, 200, status_json());
    }

    if (sscanf(url, "/tally/%d/%15[a-zA-Z]%n", &n, word, &len) == 2 && !url[len]) {
        int t = parse_tally(word);
        if (n < 1 || n > g.cfg.cameras || t < 0) {
            char msg[64];
            snprintf(msg, sizeof msg, "usage : /tally/<1-%d>/<off|pvw|pgm>", g.cfg.cameras);
            return reply(conn, 400, error_json(msg));
        }
        pthread_mutex_lock(&g.lock);
        g.cam[n - 1].tally = t;
        pthread_cond_broadcast(&g.cond);
        pthread_mutex_unlock(&g.lock);
        return reply(conn, 200, status_json());
    }

    if (sscanf(url, "/label/%d%n", &n, &len) == 1 && !url[len]) {
        if (n < 1 || n > g.cfg.cameras)
            return reply(conn, 400, range_error());
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

    if (sscanf(url, "/input/%d%n", &n, &len) == 1 && !url[len]) {
        /* Change one input without disturbing the others: new SRT URL (empty:
           input disabled) and/or SRT latency. Only this input reconnects.
           GET ?url=...&latency_ms=... or form body url=...&latency_ms=... */
        if (n < 1 || n > g.cfg.cameras)
            return reply(conn, 400, range_error());
        char newurl[sizeof g.cam[0].url], lat[16];
        bool has_url = form_value(conn, rq, "url", newurl, sizeof newurl);
        bool has_lat = form_value(conn, rq, "latency_ms", lat, sizeof lat);
        if (!has_url && !has_lat)
            return reply(conn, 400, error_json("url et/ou latency_ms manquants"));
        int newlat = has_lat && lat[0] ? atoi(lat) : -1;
        if (has_lat && (newlat < -1 || newlat > 10000))
            return reply(conn, 400, error_json("latency_ms : 0 à 10000"));
        struct cam *c = &g.cam[n - 1];
        pthread_mutex_lock(&g.lock);
        if (has_url && strcmp(c->url, newurl)) {
            snprintf(c->url, sizeof c->url, "%s", newurl);
            c->reload = 1;
            logm("cam%d : URL changée (%s)", n, newurl[0] ? newurl : "entrée désactivée");
        }
        if (has_lat && c->latency_ms != newlat) {
            c->latency_ms = newlat;
            c->reload = 1;
            logm("cam%d : latence changée (%d ms)", n,
                 newlat >= 0 ? newlat : g.cfg.srt_latency_ms);
        }
        pthread_cond_broadcast(&g.cond);
        pthread_mutex_unlock(&g.lock);
        return reply(conn, 200, status_json());
    }

    return reply(conn, 404, error_json("routes : /status /select/N /output/M/select/N "
                                       "/tally/N/off|pvw|pgm /label/N /input/N"));
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

static struct MHD_Daemon *httpd;

bool http_start(int port)
{
    httpd = MHD_start_daemon(
        MHD_USE_INTERNAL_POLLING_THREAD | MHD_USE_ERROR_LOG, (uint16_t)port, NULL, NULL,
        http_cb, NULL, MHD_OPTION_NOTIFY_COMPLETED, http_done, NULL,
        MHD_OPTION_CONNECTION_TIMEOUT, (unsigned)10, MHD_OPTION_END);
    if (!httpd)
        logm("HTTP : impossible d'écouter sur le port %d", port);
    else
        logm("HTTP : API sur le port %d", port);
    return httpd != NULL;
}

void http_stop(void)
{
    if (httpd)
        MHD_stop_daemon(httpd);
    httpd = NULL;
}
