/*
 * ptzview — shared types, global state and functions of the modules.
 *
 * Modules (see README, "Organisation du code"):
 *   main.c       start-up, periodic stats line, shutdown
 *   util.c       time, log, threads, text buffer, JSON strings
 *   sysinfo.c    hardware figures (memory, CMA, temperature)
 *   config.c     defaults and ptzview.conf parsing
 *   srt_hooks.c  libsrt workarounds and receiver SRT stats (ADR 0012, 0013)
 *   input.c      one thread per input: SRT reception + hardware decoding
 *   kms.c        DRM/KMS output: planes, framebuffers, atomic commits
 *   osd.c        overlays drawn with cairo (tally, UMD, NO SIGNAL)
 *   display.c    display thread: shows the selected camera
 *   http.c       local HTTP API
 */
#ifndef PTZVIEW_H
#define PTZVIEW_H

#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <srt/srt.h>

/* Size of the input table; the number used is the "cameras" setting. */
#define MAX_CAMS 16
#define LABEL_MAX 96

/* ------------------------------------------------------------------ */
/* Types et état global                                                */
/* ------------------------------------------------------------------ */

typedef enum { TALLY_OFF = 0, TALLY_PVW, TALLY_PGM } tally_t;
extern const char *const tally_name[];

typedef enum { ST_CONNECTING = 0, ST_CONNECTED, ST_STREAMING, ST_WAITING, ST_DISABLED } cstate_t;
extern const char *const state_name[];

struct cam {
    int idx;
    char url[512];
    int latency_ms;           /* SRT latency of this input, -1: [general] value */
    SRTSOCKET srt_sock;       /* libsrt socket of the open input (g.lock), or invalid */
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
    /* set by POST /input/N: drop the current connection and use the new URL */
    volatile int reload;
    char prev_err[160];
    int64_t prev_err_log_us;
};

struct config {
    int srt_latency_ms, connect_timeout_ms, stall_timeout_ms, reconnect_ms;
    char hwaccel[32], hwaccel_device[128];
    int extra_hw_frames;
    char drm_device[64], connector[32], hdmi_mode[32], video_plane[16];
    int cameras;              /* inputs used (1..MAX_CAMS) */
    int http_port, start_camera;
    char font[64];
    double umd_off_alpha;
    int stats_interval_s, rt_priority;
    char loglevel[16];
};

struct state {
    struct config cfg;
    struct cam cam[MAX_CAMS];
    pthread_mutex_t lock;
    pthread_cond_t cond;
    int selected;             /* 0..cfg.cameras-1 */
    int64_t switch_req_us;
    double last_switch_ms;
    volatile sig_atomic_t quit;
    bool no_display;
    AVBufferRef *hwdev;
    int64_t start_us;
    char output_desc[64];
};

/* defined in main.c */
extern struct state g;

/* util.c */
int64_t now_us(void);
void logm(const char *fmt, ...);
void sleep_ms(int ms);
void set_rt(void);

/* tampon de texte extensible */
struct sbuf { char *b; size_t n, cap; };
void sb_printf(struct sbuf *s, const char *fmt, ...);
void sb_json_str(struct sbuf *s, const char *str);
void clean_label(char *dst, const char *src);

/* sysinfo.c */
long meminfo_kb(const char *key);
double soc_temp(void);

/* config.c */
void config_defaults(void);
int load_config(const char *path);
int parse_tally(const char *s);

/* srt_hooks.c */
void srt_hooks_opening(struct cam *c);
void forget_srt_sock(struct cam *c);
void srt_json(struct sbuf *s, SRTSOCKET sock);

/* input.c */
void *cam_thread(void *arg);

/* display.c */
void *display_thread(void *arg);

/* kms.c (rest of the KMS interface in kms.h) */
int kms_init(void);
void kms_close(void);

/* http.c */
bool http_start(int port);
void http_stop(void);

#endif
