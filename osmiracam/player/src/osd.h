/* osd.h — overlay state and drawing (osd.c). */
#ifndef PTZVIEW_OSD_H
#define PTZVIEW_OSD_H

#include "ptzview.h"

struct osd_state {
    int sel;
    tally_t tally;
    bool nosig;
    char label[LABEL_MAX];
};

bool osd_differs(const struct osd_state *a, const struct osd_state *b);
/* draws the overlays into OSD buffer buf of an output (out->ov[buf]) */
struct kms_out;
void osd_render(struct kms_out *out, int buf, const struct osd_state *o);

#endif
