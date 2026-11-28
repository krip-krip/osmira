/* display.c — one display thread per output: shows the camera selected for
 * that output and its overlays, at the pace of its own screen (vblank). */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "kms.h"
#include "osd.h"

bool input_shown(int idx)
{
    for (int i = 0; i < g.cfg.outputs; i++)
        if (g.out[i].connected && g.out[i].selected == idx)
            return true;
    return false;
}

/* ------------------------------------------------------------------ */
/* Thread d'affichage                                                  */
/* ------------------------------------------------------------------ */

void *display_thread(void *arg)
{
    const int oi = (int)(intptr_t)arg;
    struct kms_out *o = &ko[oi];
    struct output *out = &g.out[oi];
    const char *tag = out_tag(oi);
    char name[24];                 /* thread names: 15 characters at most */
    if (oi)
        snprintf(name, sizeof name, "display%d", oi + 1);
    else
        snprintf(name, sizeof name, "display");
    pthread_setname_np(pthread_self(), name);
    set_rt();

    AVFrame *cur = NULL;
    uint32_t cur_fb = 0;
    int shown_cam = -1;
    uint64_t shown_seq = 0;
    struct osd_state drawn;
    bool drawn_valid = false;
    int64_t last_err_log = 0;

    memset(&drawn, 0, sizeof drawn);
    pthread_mutex_lock(&g.lock);
    while (!g.quit) {
        const int sel = out->selected;
        struct cam *c = &g.cam[sel];
        const int64_t t = now_us();
        struct osd_state want;
        memset(&want, 0, sizeof want);
        want.sel = sel;
        want.tally = c->tally;
        snprintf(want.label, sizeof want.label, "%s", c->label);
        want.nosig = !(c->state == ST_STREAMING &&
                       t - c->last_frame_us < (int64_t)g.cfg.stall_timeout_ms * 1000);

        bool osd_dirty = !drawn_valid || osd_differs(&want, &drawn) || o->osd_force;
        bool new_frame = c->latest && c->seq && (sel != shown_cam || c->seq != shown_seq);
        bool blank = !c->latest && sel != shown_cam;

        if (!osd_dirty && !new_frame && !blank) {
            struct timespec ts;
            clock_gettime(CLOCK_MONOTONIC, &ts);
            ts.tv_nsec += 100 * 1000000;
            if (ts.tv_nsec >= 1000000000) {
                ts.tv_sec++;
                ts.tv_nsec -= 1000000000;
            }
            pthread_cond_timedwait(&g.cond, &g.lock, &ts);
            continue;
        }

        AVFrame *nf = NULL;
        uint64_t nseq = 0;
        if (new_frame) {
            nf = av_frame_clone(c->latest);
            nseq = c->seq;
        }
        const int64_t sw_req = sel != shown_cam ? out->switch_req_us : 0;
        pthread_mutex_unlock(&g.lock);

        uint32_t nfb = 0;
        if (nf && fb_from_frame(nf, &nfb) < 0) {
            av_frame_free(&nf);
            shown_seq = nseq;          /* on attend l'image suivante */
            usleep(20000);
        }
        if (nf && !o->video_ok && kms_pick_planes(o, nfb, nf) < 0) {
            drmModeRmFB(kd.fd, nfb);
            av_frame_free(&nf);
            shown_seq = nseq;
            sleep_ms(1000);
            pthread_mutex_lock(&g.lock);
            continue;
        }
        osd_dirty |= o->osd_force;
        int ob = -1;
        if (osd_dirty) {
            ob = o->ov_cur ^ 1;
            osd_render(o, ob, &want);
        }

        drmModeAtomicReq *req = drmModeAtomicAlloc();
        if (nf)
            kms_set_video(req, o, o->vp, nfb, nf);
        else if (blank && o->vp >= 0)
            kms_plane_disable(req, &kd.pl[o->vp]);
        if (o->disable_pending >= 0)
            kms_plane_disable(req, &kd.pl[o->disable_pending]);
        if (ob >= 0)
            kms_set_osd(req, o, o->op, o->ov[ob].fb);
        int ret = drmModeAtomicCommit(kd.fd, req, 0, NULL);   /* bloquant : rend la main après le vblank */
        int err = errno;
        drmModeAtomicFree(req);

        if (ret) {
            if (now_us() - last_err_log > 5000000) {
                logm("%sDRM : commit refusé : %s", tag, strerror(err));
                last_err_log = now_us();
            }
            if (nf) {
                drmModeRmFB(kd.fd, nfb);
                av_frame_free(&nf);
                shown_seq = nseq;
            }
            usleep(20000);
            pthread_mutex_lock(&g.lock);
            continue;
        }

        if (o->disable_pending >= 0) {
            /* plan coupé : il redevient libre pour les autres sorties */
            pthread_mutex_lock(&kd.lock);
            kd.pl[o->disable_pending].owner = -1;
            pthread_mutex_unlock(&kd.lock);
            o->disable_pending = -1;
        }
        if (ob >= 0) {
            o->ov_cur = ob;
            drawn = want;
            drawn_valid = true;
            o->osd_force = false;
        }
        double sw_ms = -1;
        if (nf || blank) {
            if (cur) {
                drmModeRmFB(kd.fd, cur_fb);
                av_frame_free(&cur);
            }
            cur = nf;
            cur_fb = nfb;
            if (sel != shown_cam) {
                if (shown_cam < 0)
                    logm("%saffichage : première image (cam%d)", tag, sel + 1);
                else if (sw_req) {
                    sw_ms = (now_us() - sw_req) / 1000.0;
                    logm("%sbascule cam%d -> cam%d : %.1f ms après la requête%s", tag,
                         shown_cam + 1, sel + 1, sw_ms, blank ? " (pas d'image : écran noir)" : "");
                }
            }
            shown_cam = sel;
            shown_seq = nf ? nseq : 0;
        }
        pthread_mutex_lock(&g.lock);
        if (sw_ms >= 0)
            out->last_switch_ms = sw_ms;
    }
    pthread_mutex_unlock(&g.lock);

    if (cur) {
        drmModeRmFB(kd.fd, cur_fb);
        av_frame_free(&cur);
    }
    return NULL;
}
