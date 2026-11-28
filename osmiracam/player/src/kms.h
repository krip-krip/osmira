/* kms.h — DRM/KMS output state and functions shared by kms.c, osd.c and display.c.
 *
 * One DRM device (kd) drives up to MAX_OUTPUTS outputs (ko[]). Each output has
 * its own connector, CRTC, planes and OSD buffers; a plane belongs to one
 * output at a time (plane_info.owner). */
#ifndef PTZVIEW_KMS_H
#define PTZVIEW_KMS_H

#include <drm_fourcc.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#include <cairo.h>

#include "ptzview.h"

#define MAX_PLANES 32

struct plane_info {
    uint32_t id;
    int type;                      /* 0 overlay, 1 primary, 2 cursor */
    bool nv12, argb;
    uint32_t possible_crtcs;       /* bit i: usable on CRTC index i */
    int owner;                     /* output using it, -1: free (kd.lock) */
    uint32_t fb_id, crtc_id, src_x, src_y, src_w, src_h, crtc_x, crtc_y, crtc_w, crtc_h;
    uint32_t zpos, color_enc, color_range;
    uint64_t zmin, zmax;
    uint64_t enc601, enc709, enc2020, rng_lim, rng_full;
    bool has_601, has_709, has_2020, has_lim, has_full;
};

struct dumb { uint32_t handle, pitch, fb; uint64_t size; uint8_t *map; };

/* The DRM device, shared by the outputs. */
struct kms_dev {
    int fd;
    struct plane_info pl[MAX_PLANES];
    int npl;
    /* Protects plane owners and fb_from_frame(): importing the same dmabuf
     * twice on one DRM fd gives the same GEM handle, so two outputs showing
     * the same camera must not close it under each other. */
    pthread_mutex_t lock;
};

/* One output: only its display thread touches it once kms_init() is done. */
struct kms_out {
    int idx;                       /* 0..MAX_OUTPUTS-1 */
    bool on;                       /* screen found and modeset done */
    uint32_t conn, crtc;
    int crtc_idx;
    drmModeModeInfo mode;
    uint32_t mode_blob;
    uint32_t conn_crtc_prop, crtc_mode_prop, crtc_active_prop;
    int vp, op;                    /* indices dans kd.pl[] des plans vidéo / OSD */
    int disable_pending;           /* plan à désactiver au prochain commit, -1 sinon */
    bool video_ok, osd_force;
    int w, h;
    struct dumb ov[2];
    int ov_cur;
    cairo_surface_t *surf;
};

extern struct kms_dev kd;
extern struct kms_out ko[MAX_OUTPUTS];

void kms_plane_disable(drmModeAtomicReq *r, const struct plane_info *p);
void kms_set_osd(drmModeAtomicReq *r, const struct kms_out *o, int op, uint32_t fb);
void kms_set_video(drmModeAtomicReq *r, const struct kms_out *o, int vp, uint32_t fb,
                   const AVFrame *f);
/* crée un framebuffer DRM à partir d'une image DRM PRIME (zéro copie) */
int fb_from_frame(const AVFrame *f, uint32_t *fb);
/* au premier affichage : cherche (TEST_ONLY) une paire de plans vidéo/OSD acceptée */
int kms_pick_planes(struct kms_out *o, uint32_t fb, const AVFrame *f);

#endif
