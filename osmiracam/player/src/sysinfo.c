/* sysinfo.c — hardware figures read from the system (memory, CMA, temperature).
 * Machine-specific readings live here only. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ptzview.h"

long meminfo_kb(const char *key)
{
    FILE *f = fopen("/proc/meminfo", "r");
    char line[128];
    long v = -1;
    size_t kl = strlen(key);
    if (!f)
        return -1;
    while (fgets(line, sizeof line, f))
        if (!strncmp(line, key, kl) && line[kl] == ':') {
            v = strtol(line + kl + 1, NULL, 10);
            break;
        }
    fclose(f);
    return v;
}

double soc_temp(void)
{
    FILE *f = fopen("/sys/class/thermal/thermal_zone0/temp", "r");
    long v = 0;
    if (!f)
        return -1;
    if (fscanf(f, "%ld", &v) != 1)
        v = -1000;
    fclose(f);
    return v / 1000.0;
}
