#!/data/data/com.termux/files/usr/bin/sh
# ponytail: pgrep-based liveness check + am-nudge restart, per-check global lock not needed (cron serializes runs 5min apart)
HOME_DIR=/data/data/com.termux/files/home
LOG="$HOME_DIR/watchdog.log"
STATE_DIR="$HOME_DIR/state"
WIFI_STATE_FILE="$STATE_DIR/wifi-alert-state.txt"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
mkdir -p "$STATE_DIR"
. "$HOME_DIR/scripts/lib.sh"

# ponytail: reafirma el techo de CPU en cada pasada, barato e idempotente -
# un nucleo que se reengancha via hotplug vuelve a su max de fabrica y el
# boot script (una sola vez al arrancar) no lo pilla
sh "$HOME_DIR/scripts/cpu-limit.sh"

if ! pgrep -x sshd >/dev/null 2>&1; then
  echo "$(ts) sshd down, restarting" >> "$LOG"
  termux-wake-lock
  sshd
fi

if ! grep -q '^ *tun0:' /proc/net/dev 2>/dev/null; then
  echo "$(ts) tun0 down, forzando reconexion de tailscale" >> "$LOG"
  # ponytail: arrancar el servicio VPN directamente (sin pasar por la
  # MainActivity) reconecta de verdad y nunca abre pantalla - evita el
  # riesgo de que un toque/tecla ajeno aterrice sobre el interruptor de
  # Tailscale (paso varias veces con `am start` a la MainActivity durante
  # depuracion por USB, ver CONTEXT.md). force-stop se probo antes y NO
  # vale: Android trata un force-stop como "quedate parado" y ni el
  # mecanismo de Always-on VPN lo reinicia solo.
  if ! su -c "am start-foreground-service -n com.tailscale.ipn/.IPNService" >> "$LOG" 2>&1; then
    echo "$(ts) su no disponible, fallback a abrir la app (menos seguro)" >> "$LOG"
    am start -n com.tailscale.ipn/.MainActivity >> "$LOG" 2>&1
  fi
fi

# ponytail: comprobacion de wifi independiente del tun0 (visto en real:
# ~20min sin red mientras el pc estaba suspendido) - nudge a tailscale
# no sirve de nada si el problema es el wifi de verdad por debajo
prev_wifi=$(cat "$WIFI_STATE_FILE" 2>/dev/null || echo up)
wifi_state=$(termux-wifi-connectioninfo 2>/dev/null | jq -r '.supplicant_state' 2>/dev/null)

if [ -n "$wifi_state" ] && [ "$wifi_state" != "COMPLETED" ]; then
  echo "$(ts) wifi caido (estado=$wifi_state), reiniciando wifi" >> "$LOG"
  echo "down" > "$WIFI_STATE_FILE"
  termux-wifi-enable false >> "$LOG" 2>&1
  sleep 3
  termux-wifi-enable true >> "$LOG" 2>&1
  # job de un solo disparo: avisa en cuanto Android detecte red disponible,
  # en vez de esperar hasta el siguiente tick del cron (5 min). El propio
  # script NO se reprograma a si mismo (ver comentario en el).
  termux-job-scheduler --script "$HOME_DIR/scripts/wifi-recovered-notify.sh" --job-id 900 --network any --persisted true >> "$LOG" 2>&1
elif [ "$prev_wifi" = "down" ]; then
  echo "$(ts) wifi recuperado, avisando" >> "$LOG"
  send_telegram "El WiFi del J5 se habia caido y ya se ha reconectado solo."
  echo "up" > "$WIFI_STATE_FILE"
else
  echo "up" > "$WIFI_STATE_FILE"
fi

if ! pgrep -f telegram-chat.py >/dev/null 2>&1; then
  echo "$(ts) telegram-chat down, restarting" >> "$LOG"
  termux-wake-lock
  bash "$HOME_DIR/scripts/start-telegram-chat.sh"
fi

# ponytail: deteccion del aviso intermitente de salud de Tailscale (relay/nsq
# reportado por el usuario, diagnosticado 2026-09-03/04: "Relay server
# unavailable" transitorio). No hay CLI `tailscale` en el build Android ni
# socket de LocalAPI expuesto; el unico rastro es el logcat del proceso de
# la app, que solo es legible con root desde Termux (unica excepcion de
# solo-lectura a la politica de evitar su en cron - justificada porque no
# hay otra forma de capturar el texto exacto del aviso). Se descartan
# wantrunning-false/warming-up: son efecto esperado de este mismo script al
# reconectar tailscale, no un fallo real.
TS_HEALTH_STATE="$STATE_DIR/tailscale-health-since.txt"
now_epoch=$(date '+%s')
since_epoch=$(cat "$TS_HEALTH_STATE" 2>/dev/null || echo "$now_epoch")
# ponytail: una sola llamada a logcat, reusada para los dos greps de abajo
# (salud de Tailscale + kills por falta de RAM) en vez de invocar logcat
# dos veces por pasada
new_logcat=$(su -c "logcat -d -b all -T $since_epoch" 2>/dev/null)
echo "$now_epoch" > "$TS_HEALTH_STATE"
health_line=$(echo "$new_logcat" | grep 'gojni.*warnable=' | grep 'error:' | grep -Ev 'warnable=(wantrunning-false|warming-up)' | tail -1)
if [ -n "$health_line" ]; then
  echo "$(ts) tailscale health warning: $health_line" >> "$LOG"
  send_telegram "Aviso de salud de Tailscale en el J5: $(echo "$health_line" | sed 's/.*gojni *: *//')"
fi

# ponytail: diagnostico proactivo de quedarse sin RAM - el incidente del
# 2026-09-02 (Tailscale/sshd muertos 14h) fue el low-memory-killer del
# sistema actuando sin dejar ningun rastro claro hasta mirar logcat a mano
# con root. Dos avisos independientes: (1) reactivo, si el logcat de este
# tramo muestra un proceso matado por falta de memoria, con el nombre
# exacto; (2) proactivo, por umbral de RAM libre en /proc/meminfo (no
# necesita root), con histeresis para no repetir en el filo.
kill_line=$(echo "$new_logcat" | grep -Ei 'lowmemorykiller|Out of memory|Killed process' | tail -1)
if [ -n "$kill_line" ]; then
  echo "$(ts) proceso matado por falta de RAM: $kill_line" >> "$LOG"
  send_telegram "El sistema del J5 acaba de matar un proceso por falta de RAM: $(echo "$kill_line" | sed 's/^.*: *//' | cut -c1-200)"
fi

LOWMEM_STATE="$STATE_DIR/lowmem-alert-state.txt"
mem_avail_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null)
prev_lowmem=$(cat "$LOWMEM_STATE" 2>/dev/null || echo ok)
if [ -n "$mem_avail_kb" ] && [ "$mem_avail_kb" -lt 102400 ]; then
  if [ "$prev_lowmem" = "ok" ]; then
    echo "$(ts) RAM libre baja (${mem_avail_kb}kB), aviso" >> "$LOG"
    send_telegram "Aviso: RAM libre baja en el J5 (${mem_avail_kb}kB), riesgo de que el sistema mate algun proceso pronto."
  fi
  echo "low" > "$LOWMEM_STATE"
elif [ -n "$mem_avail_kb" ] && [ "$mem_avail_kb" -gt 153600 ]; then
  echo "ok" > "$LOWMEM_STATE"
fi
