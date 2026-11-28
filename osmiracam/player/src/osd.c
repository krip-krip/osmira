/* osd.c — overlays drawn with cairo: tally border, UMD, NO SIGNAL. */
#include <math.h>
#include <string.h>

#include "kms.h"
#include "osd.h"

/* ------------------------------------------------------------------ */
/* OSD : tally + UMD + NO SIGNAL (cairo, uniquement sur changement)    */
/* ------------------------------------------------------------------ */

bool osd_differs(const struct osd_state *a, const struct osd_state *b)
{
    return a->sel != b->sel || a->tally != b->tally || a->nosig != b->nosig ||
           strcmp(a->label, b->label);
}

static void text_centered(cairo_t *cr, const char *txt, double size, double maxw, double cx,
                          double cy)
{
    cairo_text_extents_t te;
    cairo_select_font_face(cr, g.cfg.font, CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
    cairo_set_font_size(cr, size);
    cairo_text_extents(cr, txt, &te);
    if (te.x_advance > maxw && te.x_advance > 0) {
        cairo_set_font_size(cr, size * maxw / te.x_advance);
        cairo_text_extents(cr, txt, &te);
    }
    cairo_move_to(cr, cx - (te.x_bearing + te.width / 2), cy - (te.y_bearing + te.height / 2));
    cairo_show_text(cr, txt);
}

void osd_render(struct kms_out *out, int buf, const struct osd_state *o)
{
    const double W = out->w, H = out->h, s = H / 1080.0;
    cairo_t *cr = cairo_create(out->surf);
    cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
    cairo_paint(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);

    double r = 0, gg = 0, b = 0;
    if (o->tally == TALLY_PGM) { r = 0xE0 / 255.0; gg = 0; b = 0; }
    if (o->tally == TALLY_PVW) { r = 0; gg = 0xB0 / 255.0; b = 0; }

    const double bw = round(14 * s);
    if (o->tally != TALLY_OFF) {
        cairo_set_source_rgb(cr, r, gg, b);
        cairo_rectangle(cr, 0, 0, W, bw);
        cairo_rectangle(cr, 0, H - bw, W, bw);
        cairo_rectangle(cr, 0, bw, bw, H - 2 * bw);
        cairo_rectangle(cr, W - bw, bw, bw, H - 2 * bw);
        cairo_fill(cr);
    }

    /* bandeau UMD 600x70, centré en bas, 24 px au-dessus de la bordure */
    const double uw = round(600 * s), uh = round(70 * s);
    const double ux = round((W - uw) / 2), uy = round(H - bw - 24 * s - uh);
    if (o->tally == TALLY_OFF)
        cairo_set_source_rgba(cr, 0, 0, 0, g.cfg.umd_off_alpha);
    else
        cairo_set_source_rgb(cr, r, gg, b);
    cairo_rectangle(cr, ux, uy, uw, uh);
    cairo_fill(cr);
    if (o->label[0]) {
        cairo_set_source_rgb(cr, 1, 1, 1);
        text_centered(cr, o->label, 46 * s, uw - 20 * s, ux + uw / 2, uy + uh / 2);
    }

    if (o->nosig) {
        const double nw = round(560 * s), nh = round(130 * s);
        cairo_set_source_rgba(cr, 0, 0, 0, 0.65);
        cairo_rectangle(cr, round((W - nw) / 2), round((H - nh) / 2), nw, nh);
        cairo_fill(cr);
        cairo_set_source_rgb(cr, 1, 1, 1);
        text_centered(cr, "NO SIGNAL", 80 * s, nw - 40 * s, W / 2, H / 2);
    }
    cairo_destroy(cr);
    cairo_surface_flush(out->surf);

    const uint8_t *src = cairo_image_surface_get_data(out->surf);
    const int sstride = cairo_image_surface_get_stride(out->surf);
    struct dumb *d = &out->ov[buf];
    for (int y = 0; y < out->h; y++)
        memcpy(d->map + (size_t)y * d->pitch, src + (size_t)y * sstride, (size_t)out->w * 4);
}
