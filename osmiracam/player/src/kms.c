/* kms.c — DRM/KMS outputs: connectors, modes, planes, framebuffers, atomic requests. */
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

struct kms_dev kd = { .fd = -1, .lock = PTHREAD_MUTEX_INITIALIZER };
struct kms_out ko[MAX_OUTPUTS];

static void load_plane(struct plane_info *p)
{
    drmModeObjectProperties *pr = drmModeObjectGetProperties(kd.fd, p->id, DRM_MODE_OBJECT_PLANE);
    if (!pr)
        return;
    for (uint32_t i = 0; i < pr->count_props; i++) {
        drmModePropertyRes *q = drmModeGetProperty(kd.fd, pr->props[i]);
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
    drmModeObjectProperties *pr = drmModeObjectGetProperties(kd.fd, obj, type);
    uint32_t id = 0;
    if (!pr)
        return 0;
    for (uint32_t i = 0; i < pr->count_props && !id; i++) {
        drmModePropertyRes *q = drmModeGetProperty(kd.fd, pr->props[i]);
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

static void plane_full(drmModeAtomicReq *r, const struct kms_out *o, const struct plane_info *p,
                       uint32_t fb, int sw, int sh, int dx, int dy, int dw, int dh)
{
    add(r, p->id, p->fb_id, fb);
    add(r, p->id, p->crtc_id, o->crtc);
    add(r, p->id, p->src_x, 0);
    add(r, p->id, p->src_y, 0);
    add(r, p->id, p->src_w, (uint64_t)sw << 16);
    add(r, p->id, p->src_h, (uint64_t)sh << 16);
    add(r, p->id, p->crtc_x, dx);
    add(r, p->id, p->crtc_y, dy);
    add(r, p->id, p->crtc_w, dw);
    add(r, p->id, p->crtc_h, dh);
}

void kms_set_osd(drmModeAtomicReq *r, const struct kms_out *o, int op, uint32_t fb)
{
    const struct plane_info *p = &kd.pl[op];
    plane_full(r, o, p, fb, o->w, o->h, 0, 0, o->w, o->h);
    if (p->zpos)
        add(r, p->id, p->zpos, p->zmax);
}

void kms_set_video(drmModeAtomicReq *r, const struct kms_out *o, int vp, uint32_t fb,
                   const AVFrame *f)
{
    const struct plane_info *p = &kd.pl[vp];
    int sw = f->width, sh = f->height, dw, dh;
    /* conserve le rapport d'image */
    if ((int64_t)sw * o->h > (int64_t)sh * o->w) {
        dw = o->w;
        dh = (int)((int64_t)o->w * sh / sw);
    } else {
        dh = o->h;
        dw = (int)((int64_t)o->h * sw / sh);
    }
    plane_full(r, o, p, fb, sw, sh, (o->w - dw) / 2, (o->h - dh) / 2, dw, dh);
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

static int dumb_create(struct dumb *d, int w, int h)
{
    struct drm_mode_create_dumb c = { .width = w, .height = h, .bpp = 32 };
    if (drmIoctl(kd.fd, DRM_IOCTL_MODE_CREATE_DUMB, &c))
        return -1;
    d->handle = c.handle;
    d->pitch = c.pitch;
    d->size = c.size;
    uint32_t hd[4] = { c.handle }, p[4] = { c.pitch }, o[4] = { 0 };
    if (drmModeAddFB2(kd.fd, w, h, DRM_FORMAT_ARGB8888, hd, p, o, &d->fb, 0))
        return -1;
    struct drm_mode_map_dumb m = { .handle = c.handle };
    if (drmIoctl(kd.fd, DRM_IOCTL_MODE_MAP_DUMB, &m))
        return -1;
    d->map = mmap(NULL, c.size, PROT_READ | PROT_WRITE, MAP_SHARED, kd.fd, m.offset);
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
        drmModeRmFB(kd.fd, d->fb);
    if (d->handle) {
        struct drm_mode_destroy_dumb x = { .handle = d->handle };
        drmIoctl(kd.fd, DRM_IOCTL_MODE_DESTROY_DUMB, &x);
    }
    memset(d, 0, sizeof *d);
}

static const char *conn_name(drmModeConnector *c, char *buf, size_t n)
{
    const char *t = drmModeGetConnectorTypeName(c->connector_type);
    snprintf(buf, n, "%s-%u", t ? t : "?", c->connector_type_id);
    return buf;
}

static bool pick_mode(drmModeConnector *c, const char *m, drmModeModeInfo *out)
{
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

/* Can output o use plane i (right CRTC, not taken by another output)? (kd.lock) */
static bool plane_usable(const struct kms_out *o, int i)
{
    const struct plane_info *p = &kd.pl[i];
    return (p->possible_crtcs & (1u << o->crtc_idx)) && (p->owner < 0 || p->owner == o->idx);
}

static int open_device(drmModeRes **res)
{
    char path[64];
    for (int i = 0; i < 8; i++) {
        if (strcmp(g.cfg.drm_device, "auto"))
            snprintf(path, sizeof path, "%s", g.cfg.drm_device);
        else
            snprintf(path, sizeof path, "/dev/dri/card%d", i);
        int fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd >= 0) {
            *res = drmModeGetResources(fd);
            if (*res && (*res)->count_connectors && (*res)->count_crtcs) {
                kd.fd = fd;
                break;
            }
            if (*res)
                drmModeFreeResources(*res);
            *res = NULL;
            close(fd);
        }
        if (strcmp(g.cfg.drm_device, "auto"))
            break;
    }
    if (kd.fd < 0) {
        logm("DRM : aucune carte d'affichage trouvée (drm_device=%s)", g.cfg.drm_device);
        return -1;
    }
    if (drmSetClientCap(kd.fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1) ||
        drmSetClientCap(kd.fd, DRM_CLIENT_CAP_ATOMIC, 1)) {
        logm("DRM : mode atomique non disponible");
        return -1;
    }
    return 0;
}

static void load_planes(void)
{
    drmModePlaneRes *pr = drmModeGetPlaneResources(kd.fd);
    if (!pr)
        return;
    for (uint32_t i = 0; i < pr->count_planes && kd.npl < MAX_PLANES; i++) {
        drmModePlane *p = drmModeGetPlane(kd.fd, pr->planes[i]);
        if (!p)
            continue;
        struct plane_info *pi = &kd.pl[kd.npl++];
        memset(pi, 0, sizeof *pi);
        pi->id = p->plane_id;
        pi->possible_crtcs = p->possible_crtcs;
        pi->owner = -1;
        for (uint32_t f = 0; f < p->count_formats; f++) {
            if (p->formats[f] == DRM_FORMAT_NV12) pi->nv12 = true;
            if (p->formats[f] == DRM_FORMAT_ARGB8888) pi->argb = true;
        }
        load_plane(pi);
        drmModeFreePlane(p);
    }
    drmModeFreePlaneResources(pr);
}

static void list_connectors(drmModeRes *res)
{
    char name[32];
    logm("DRM : connecteurs :");
    for (int i = 0; i < res->count_connectors; i++) {
        drmModeConnector *c = drmModeGetConnector(kd.fd, res->connectors[i]);
        if (!c)
            continue;
        logm("   %s (%s)", conn_name(c, name, sizeof name),
             c->connection == DRM_MODE_CONNECTED ? "connecté" : "déconnecté");
        drmModeFreeConnector(c);
    }
}

/* Mode, CRTC, OSD plane and buffers of output o on connector conn, then modeset. */
static int output_setup(struct kms_out *o, drmModeRes *res, drmModeConnector *conn,
                        uint32_t *crtcs_used)
{
    const struct output_cfg *oc = &g.cfg.out[o->idx];
    const char *tag = out_tag(o->idx);
    char name[32];
    conn_name(conn, name, sizeof name);
    o->conn = conn->connector_id;

    if (!pick_mode(conn, oc->hdmi_mode, &o->mode)) {
        logm("%sDRM : mode « %s » introuvable sur %s. Modes disponibles :", tag, oc->hdmi_mode,
             name);
        for (int i = 0; i < conn->count_modes; i++)
            logm("   %2d : %dx%d%s@%u", i, conn->modes[i].hdisplay, conn->modes[i].vdisplay,
                 conn->modes[i].flags & DRM_MODE_FLAG_INTERLACE ? "i" : "",
                 conn->modes[i].vrefresh);
        return -1;
    }
    o->w = o->mode.hdisplay;
    o->h = o->mode.vdisplay;

    /* CRTC pas encore pris par une autre sortie */
    o->crtc_idx = -1;
    for (int e = 0; e < conn->count_encoders && o->crtc_idx < 0; e++) {
        drmModeEncoder *enc = drmModeGetEncoder(kd.fd, conn->encoders[e]);
        if (!enc)
            continue;
        for (int i = 0; i < res->count_crtcs; i++)
            if ((enc->possible_crtcs & (1u << i)) && !(*crtcs_used & (1u << i))) {
                o->crtc_idx = i;
                o->crtc = res->crtcs[i];
                break;
            }
        drmModeFreeEncoder(enc);
    }
    if (o->crtc_idx < 0) {
        logm("%sDRM : pas de CRTC pour %s", tag, name);
        return -1;
    }

    o->conn_crtc_prop = obj_prop(o->conn, DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID");
    o->crtc_mode_prop = obj_prop(o->crtc, DRM_MODE_OBJECT_CRTC, "MODE_ID");
    o->crtc_active_prop = obj_prop(o->crtc, DRM_MODE_OBJECT_CRTC, "ACTIVE");
    if (drmModeCreatePropertyBlob(kd.fd, &o->mode, sizeof o->mode, &o->mode_blob)) {
        logm("%sDRM : création du blob de mode impossible", tag);
        return -1;
    }

    /* plan OSD provisoire : premier overlay ARGB, sinon n'importe quel plan ARGB */
    int nusable = 0;
    pthread_mutex_lock(&kd.lock);
    for (int i = 0; i < kd.npl; i++)
        nusable += plane_usable(o, i);
    for (int i = 0; i < kd.npl && o->op < 0; i++)
        if (plane_usable(o, i) && kd.pl[i].type == 0 && kd.pl[i].argb)
            o->op = i;
    for (int i = 0; i < kd.npl && o->op < 0; i++)
        if (plane_usable(o, i) && kd.pl[i].argb && kd.pl[i].type != 2)
            o->op = i;
    if (o->op >= 0)
        kd.pl[o->op].owner = o->idx;
    pthread_mutex_unlock(&kd.lock);
    if (o->op < 0) {
        logm("%sDRM : aucun plan ARGB8888 disponible", tag);
        return -1;
    }

    for (int i = 0; i < 2; i++)
        if (dumb_create(&o->ov[i], o->w, o->h) < 0) {
            logm("%sDRM : création du tampon OSD impossible : %s", tag, strerror(errno));
            return -1;
        }
    o->surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, o->w, o->h);

    /* modeset initial : écran noir + OSD ; les plans libres de ce CRTC sont coupés,
       ceux des autres sorties ne sont pas touchés */
    drmModeAtomicReq *r = drmModeAtomicAlloc();
    add(r, o->conn, o->conn_crtc_prop, o->crtc);
    add(r, o->crtc, o->crtc_mode_prop, o->mode_blob);
    add(r, o->crtc, o->crtc_active_prop, 1);
    pthread_mutex_lock(&kd.lock);
    for (int i = 0; i < kd.npl; i++)
        if (i != o->op && plane_usable(o, i) && kd.pl[i].owner < 0)
            kms_plane_disable(r, &kd.pl[i]);
    pthread_mutex_unlock(&kd.lock);
    kms_set_osd(r, o, o->op, o->ov[0].fb);
    int ret = drmModeAtomicCommit(kd.fd, r, DRM_MODE_ATOMIC_ALLOW_MODESET, NULL);
    drmModeAtomicFree(r);
    if (ret) {
        logm("%sDRM : modeset impossible : %s%s", tag, strerror(errno),
             errno == EACCES ? " (un autre programme utilise l'écran ? mpv ?)" : "");
        return -1;
    }
    *crtcs_used |= 1u << o->crtc_idx;
    o->ov_cur = 0;
    o->on = true;
    struct output *out = &g.out[o->idx];
    snprintf(out->desc, sizeof out->desc, "%s %dx%d@%u", name, o->w, o->h, o->mode.vrefresh);
    out->connected = true;
    logm("%sDRM : %s, %d plans utilisables, OSD sur le plan %u", tag, out->desc, nusable,
         kd.pl[o->op].id);
    return 0;
}

int kms_init(void)
{
    drmModeRes *res = NULL;
    char name[32];

    for (int i = 0; i < MAX_OUTPUTS; i++) {
        struct kms_out *o = &ko[i];
        memset(o, 0, sizeof *o);
        o->idx = i;
        o->vp = o->op = o->disable_pending = -1;
    }
    if (open_device(&res) < 0) {
        if (res)
            drmModeFreeResources(res);
        return -1;
    }
    load_planes();

    /* connecteur de chaque sortie : d'abord les noms donnés, puis « auto » =
       le premier écran branché qui n'est pas déjà pris */
    drmModeConnector *conn[MAX_OUTPUTS] = { 0 };
    for (int pass = 0; pass < 2; pass++)
        for (int o = 0; o < g.cfg.outputs; o++) {
            const char *want = g.cfg.out[o].connector;
            bool is_auto = !want[0] || !strcasecmp(want, "auto");
            if (pass != is_auto)
                continue;
            for (int i = 0; i < res->count_connectors && !conn[o]; i++) {
                drmModeConnector *c = drmModeGetConnector(kd.fd, res->connectors[i]);
                if (!c)
                    continue;
                bool taken = false;
                for (int j = 0; j < g.cfg.outputs; j++)
                    taken |= conn[j] && conn[j]->connector_id == c->connector_id;
                conn_name(c, name, sizeof name);
                bool match = is_auto ? c->connection == DRM_MODE_CONNECTED : !strcmp(name, want);
                if (match && !taken && c->count_modes)
                    conn[o] = c;
                else
                    drmModeFreeConnector(c);
            }
            if (!conn[o])
                logm("%sDRM : pas d'écran (connecteur « %s » introuvable, déjà pris ou sans mode)",
                     out_tag(o), want);
        }

    uint32_t crtcs_used = 0;
    int on = 0;
    for (int o = 0; o < g.cfg.outputs; o++) {
        if (!conn[o])
            continue;
        if (output_setup(&ko[o], res, conn[o], &crtcs_used) == 0)
            on++;
        else if (ko[o].op >= 0) {
            pthread_mutex_lock(&kd.lock);
            kd.pl[ko[o].op].owner = -1;
            pthread_mutex_unlock(&kd.lock);
        }
        drmModeFreeConnector(conn[o]);
    }
    if (!on)
        list_connectors(res);
    drmModeFreeResources(res);
    return on ? 0 : -1;
}

void kms_close(void)
{
    if (kd.fd < 0)
        return;
    for (int o = 0; o < MAX_OUTPUTS; o++) {
        for (int i = 0; i < 2; i++)
            dumb_destroy(&ko[o].ov[i]);
        if (ko[o].surf)
            cairo_surface_destroy(ko[o].surf);
        ko[o].surf = NULL;
        if (ko[o].mode_blob)
            drmModeDestroyPropertyBlob(kd.fd, ko[o].mode_blob);
        ko[o].mode_blob = 0;
    }
    close(kd.fd);
    kd.fd = -1;
}

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
    pthread_mutex_lock(&kd.lock);
    for (int i = 0; i < d->nb_objects; i++)
        if (drmPrimeFDToHandle(kd.fd, d->objects[i].fd, &bo[i])) {
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
    if (drmModeAddFB2WithModifiers(kd.fd, f->width, f->height, L->format, handles, pitches,
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
            drmIoctl(kd.fd, DRM_IOCTL_GEM_CLOSE, &gc);
        }
    }
    pthread_mutex_unlock(&kd.lock);
    return ret;
}

static bool vplane_allowed(const struct kms_out *o, int i)
{
    const char *v = g.cfg.out[o->idx].video_plane;
    if (!kd.pl[i].nv12 || !plane_usable(o, i))
        return false;
    if (!strcasecmp(v, "primary"))
        return kd.pl[i].type == 1;
    if (!strcasecmp(v, "overlay"))
        return kd.pl[i].type == 0;
    if (isdigit((unsigned char)v[0]))
        return kd.pl[i].id == (uint32_t)atoi(v);
    return kd.pl[i].type != 2;
}

int kms_pick_planes(struct kms_out *o, uint32_t fb, const AVFrame *f)
{
    const char *tag = out_tag(o->idx);
    int order[MAX_PLANES], n = 0;
    pthread_mutex_lock(&kd.lock);
    for (int pass = 0; pass < 2; pass++)          /* primaire d'abord, puis overlays */
        for (int i = 0; i < kd.npl; i++)
            if (vplane_allowed(o, i) && ((pass == 0) == (kd.pl[i].type == 1)))
                order[n++] = i;
    for (int a = 0; a < n; a++) {
        int vp = order[a];
        int ocand[MAX_PLANES], no = 0;
        if (o->op != vp)
            ocand[no++] = o->op;
        for (int i = 0; i < kd.npl; i++)
            if (i != vp && i != o->op && kd.pl[i].argb && kd.pl[i].type != 2 &&
                plane_usable(o, i))
                ocand[no++] = i;
        for (int b = 0; b < no; b++) {
            int op = ocand[b];
            drmModeAtomicReq *r = drmModeAtomicAlloc();
            kms_set_video(r, o, vp, fb, f);
            kms_set_osd(r, o, op, o->ov[o->ov_cur].fb);
            /* old OSD plane switched off, unless it becomes the video plane */
            if (op != o->op && o->op != vp)
                kms_plane_disable(r, &kd.pl[o->op]);
            int ret = drmModeAtomicCommit(kd.fd, r, DRM_MODE_ATOMIC_TEST_ONLY, NULL);
            int err = errno;
            drmModeAtomicFree(r);
            logm("%sDRM : essai vidéo=plan %u (%s) + OSD=plan %u : %s", tag, kd.pl[vp].id,
                 kd.pl[vp].type == 1 ? "primary" : "overlay", kd.pl[op].id,
                 ret ? strerror(err) : "OK");
            if (!ret) {
                if (op != o->op) {
                    /* l'ancien plan OSD reste à cette sortie jusqu'à sa coupure */
                    if (o->op != vp)
                        o->disable_pending = o->op;
                    o->op = op;
                    o->osd_force = true;
                }
                kd.pl[vp].owner = kd.pl[op].owner = o->idx;
                o->vp = vp;
                o->video_ok = true;
                pthread_mutex_unlock(&kd.lock);
                return 0;
            }
        }
    }
    pthread_mutex_unlock(&kd.lock);
    logm("%sDRM : aucun plan n'accepte ces images (voir video_plane dans la config)", tag);
    return -1;
}
