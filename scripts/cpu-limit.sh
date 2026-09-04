#!/data/data/com.termux/files/usr/bin/sh
# ponytail: el kernel de este hardware (Exynos 7870, SM-J530F) solo expone
# los gobernadores "userspace interactive performance" - no hay
# powersave/schedutil. En vez de cambiar de gobernador, se baja el techo
# (scaling_max_freq, de 1586MHz a 1100MHz) dejando el suelo intacto
# (546MHz, ya bajo) - recorta los picos de consumo/calor de cron+Qwen sin
# tocar el idle normal. Idempotente y pensado para llamarse repetidas
# veces (arranque + cada tick de watchdog.sh), porque un nucleo que se
# reengancha via hotplug vuelve a su max de fabrica.
# Para revertir: MAX_FREQ=1586000 y volver a correr esto, o
# reiniciar el dispositivo (no persiste solo).
MAX_FREQ=1100000
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq; do
  [ -f "$f" ] || continue
  cur=$(su -c "cat $f" 2>/dev/null)
  [ "$cur" = "$MAX_FREQ" ] && continue
  su -c "echo $MAX_FREQ > $f" >/dev/null 2>&1
done
