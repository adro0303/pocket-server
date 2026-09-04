#!/data/data/com.termux/files/usr/bin/bash
# ponytail: job de UN SOLO disparo (--network any, sin reprogramarse a si
# mismo) - lo dispara termux-job-scheduler en cuanto Android detecta red
# disponible, en vez de esperar al siguiente tick del cron de 5 min.
# NUNCA anadir aqui una llamada a termux-job-scheduler que se reprograme -
# eso crea un bucle infinito (visto en real, ~1000 iteraciones en 2 min
# antes de poder detenerlo con --cancel-all).
HOME_DIR=/data/data/com.termux/files/home
. "$HOME_DIR/scripts/lib.sh"
STATE_DIR="$HOME_DIR/state"
WIFI_STATE_FILE="$STATE_DIR/wifi-alert-state.txt"
prev=$(cat "$WIFI_STATE_FILE" 2>/dev/null || echo up)
if [ "$prev" = "down" ]; then
  send_telegram "El WiFi del J5 se habia caido y ya se ha reconectado solo."
  echo "up" > "$WIFI_STATE_FILE"
fi
