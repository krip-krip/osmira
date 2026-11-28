/* kms.h — DRM/KMS output state and functions shared by kms.c, osd.c and display.c. */
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
    uint32_t fb_id, crtc_id, src_x, src_y, src_w, src_h, crtc_x, crtc_y, crtc_w, crtc_h;
    uint32_t zpos, color_enc, color_range;
    uint64_t zmin, zmax;
    uint64_t enc601, enc709, enc2020, rng_lim, rng_full;
    bool has_601, has_709, has_2020, has_lim, has_full;
};

struct dumb { uint32_t handle, pitch, fb; uint64_t size; uint8_t *map; };

struct kms {
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
};

extern struct kms k;

void kms_plane_disable(drmModeAtomicReq *r, const struct plane_info *p);
void kms_set_osd(drmModeAtomicReq *r, int op, uint32_t fb);
void kms_set_video(drmModeAtomicReq *r, int vp, uint32_t fb, const AVFrame *f);
/* crée un framebuffer DRM à partir d'une image DRM PRIME (zéro copie) */
int fb_from_frame(const AVFrame *f, uint32_t *fb);
/* au premier affichage : cherche (TEST_ONLY) une paire de plans vidéo/OSD acceptée */
int kms_pick_planes(uint32_t fb, const AVFrame *f);

#endif
