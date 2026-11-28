/* display.c — display thread: shows the selected camera and its overlays. */
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "kms.h"
#include "osd.h"

/* ------------------------------------------------------------------ */
/* Thread d'affichage                                                  */
/* ------------------------------------------------------------------ */

void *display_thread(void *arg)
{
    (void)arg;
    pthread_setname_np(pthread_self(), "display");
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
        const int sel = g.selected;
        struct cam *c = &g.cam[sel];
        const int64_t t = now_us();
        struct osd_state want;
        memset(&want, 0, sizeof want);
        want.sel = sel;
        want.tally = c->tally;
        snprintf(want.label, sizeof want.label, "%s", c->label);
        want.nosig = !(c->state == ST_STREAMING &&
                       t - c->last_frame_us < (int64_t)g.cfg.stall_timeout_ms * 1000);

        bool osd_dirty = !drawn_valid || osd_differs(&want, &drawn) || k.osd_force;
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
        const int64_t sw_req = sel != shown_cam ? g.switch_req_us : 0;
        const double age_ms = nf ? (t - c->last_frame_us) / 1000.0 : 0;
        pthread_mutex_unlock(&g.lock);

        uint32_t nfb = 0;
        if (nf && fb_from_frame(nf, &nfb) < 0) {
            av_frame_free(&nf);
            shown_seq = nseq;          /* on attend l'image suivante */
            usleep(20000);
        }
        if (nf && !k.video_ok && kms_pick_planes(nfb, nf) < 0) {
            drmModeRmFB(k.fd, nfb);
            av_frame_free(&nf);
            shown_seq = nseq;
            sleep_ms(1000);
            pthread_mutex_lock(&g.lock);
            continue;
        }
        osd_dirty |= k.osd_force;
        int ob = -1;
        if (osd_dirty) {
            ob = k.ov_cur ^ 1;
            osd_render(ob, &want);
        }

        drmModeAtomicReq *req = drmModeAtomicAlloc();
        if (nf)
            kms_set_video(req, k.vp, nfb, nf);
        else if (blank && k.vp >= 0)
            kms_plane_disable(req, &k.pl[k.vp]);
        if (k.disable_pending >= 0)
            kms_plane_disable(req, &k.pl[k.disable_pending]);
        if (ob >= 0)
            kms_set_osd(req, k.op, k.ov[ob].fb);
        int ret = drmModeAtomicCommit(k.fd, req, 0, NULL);   /* bloquant : rend la main après le vblank */
        int err = errno;
        drmModeAtomicFree(req);

        if (ret) {
            if (now_us() - last_err_log > 5000000) {
                logm("DRM : commit refusé : %s", strerror(err));
                last_err_log = now_us();
            }
            if (nf) {
                drmModeRmFB(k.fd, nfb);
                av_frame_free(&nf);
                shown_seq = nseq;
            }
            usleep(20000);
            pthread_mutex_lock(&g.lock);
            continue;
        }

        k.disable_pending = -1;
        if (ob >= 0) {
            k.ov_cur = ob;
            drawn = want;
            drawn_valid = true;
            k.osd_force = false;
        }
        double sw_ms = -1;
        if (nf || blank) {
            if (cur) {
                drmModeRmFB(k.fd, cur_fb);
                av_frame_free(&cur);
            }
            cur = nf;
            cur_fb = nfb;
            if (sel != shown_cam) {
                if (shown_cam < 0)
                    logm("affichage : première image (cam%d)", sel + 1);
                else if (sw_req) {
                    sw_ms = (now_us() - sw_req) / 1000.0;
                    logm("bascule cam%d -> cam%d : %.1f ms après la requête%s", shown_cam + 1,
                         sel + 1, sw_ms, blank ? " (pas d'image : écran noir)" : "");
                    (void)age_ms;
                }
            }
            shown_cam = sel;
            shown_seq = nf ? nseq : 0;
        }
        pthread_mutex_lock(&g.lock);
        if (sw_ms >= 0)
            g.last_switch_ms = sw_ms;
    }
    pthread_mutex_unlock(&g.lock);

    if (cur) {
        drmModeRmFB(k.fd, cur_fb);
        av_frame_free(&cur);
    }
    return NULL;
}
