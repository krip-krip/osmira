/* kms.c — DRM/KMS output: connector, mode, planes, framebuffers, atomic requests. */
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/mman.h>
#include <unistd.h>

#include <libavutil/hwcontext_drm.h>

#include "kms.h"

/* ------------------------------------------------------------------ */
/* Affichage DRM/KMS                                                   */
/* ------------------------------------------------------------------ */

struct kms k = { .fd = -1, .vp = -1, .op = -1, .disable_pending = -1 };

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

void kms_plane_disable(drmModeAtomicReq *r, const struct plane_info *p)
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

void kms_set_osd(drmModeAtomicReq *r, int op, uint32_t fb)
{
    const struct plane_info *p = &k.pl[op];
    plane_full(r, p, fb, k.w, k.h, 0, 0, k.w, k.h);
    if (p->zpos)
        add(r, p->id, p->zpos, p->zmax);
}

void kms_set_video(drmModeAtomicReq *r, int vp, uint32_t fb, const AVFrame *f)
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

int kms_init(void)
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
            kms_plane_disable(r, &k.pl[i]);
    kms_set_osd(r, k.op, k.ov[0].fb);
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

void kms_close(void)
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
int fb_from_frame(const AVFrame *f, uint32_t *fb)
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
int kms_pick_planes(uint32_t fb, const AVFrame *f)
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
            kms_set_video(r, vp, fb, f);
            kms_set_osd(r, op, k.ov[k.ov_cur].fb);
            if (op != k.op)
                kms_plane_disable(r, &k.pl[k.op]);
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
