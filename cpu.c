#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <malloc.h>
#include <ctype.h>
#include "stats.h"
#include "trace.h"

/* The /proc manpage says units are units of 1/sysconf(_SC_CLK_TCK)
   second.  sysconf(_SC_CLK_TCK) seems to always be 100. */

/* We ignore steal and guest. */

#define KEYS \
  X(user, "event,unit=cs", "time in user mode"), \
  X(nice, "event,unit=cs", "time in user mode with low priority"), \
  X(system, "event,unit=cs", "time in system mode"), \
  X(idle, "event,unit=cs", "time in idle task"), \
  X(iowait, "event,unit=cs", "time in I/O wait"), \
  X(irq, "event,unit=cs", "time in IRQ"), \
  X(softirq, "event,unit=cs", "time in softIRQ")

static void collect_proc_stat_cpu(struct stats_type *type, char *cpu, char *rest)
{
  /* Ignore the totals line and anything not matching [0-9]+. */
  char *s = cpu;

  if (*s == 0)
    return;

  for (; *s != 0; s++)
    if (!isdigit(*s))
      return;

  struct stats *cpu_stats = get_current_stats(type, cpu);
  if (cpu_stats == NULL)
    return;

#define X(k,r...) k = 0
  unsigned long long KEYS;
#undef X

#define X(k,r...) &k
  sscanf(rest, "%llu %llu %llu %llu %llu %llu %llu", KEYS);
#undef X

#define X(k,r...) stats_set(cpu_stats, #k, k)
  KEYS;
#undef X
}

static void collect_proc_stat(struct stats_type *type)
{
  const char *path = "/proc/stat";
  FILE *file = NULL;
  char *line = NULL;
  size_t line_size = 0;

  file = fopen(path, "r");
  if (file == NULL) {
    ERROR("cannot open `%s': %m\n", path);
    goto out;
  }

  while (getline(&line, &line_size, file) >= 0) {
    char *key, *rest = line;
    key = strsep(&rest, " ");
    if (*key == 0 || rest == NULL)
      continue;

    if (strncmp(key, "cpu", 3) != 0)
      continue;

    collect_proc_stat_cpu(type, key + 3, rest);
  }

 out:
  free(line);
  if (file != NULL)
    fclose(file);
}

struct stats_type STATS_TYPE_CPU = {
  .st_name = "cpu",
  .st_collect = &collect_proc_stat,
#define X(k,o,d,r...) #k "," o ",desc=" d "; "
  .st_schema_def = STRJOIN(KEYS),
#undef X
};