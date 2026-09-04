#!/data/data/com.termux/files/usr/bin/bash
HOME_DIR="/data/data/com.termux/files/home"
source "$HOME_DIR/scripts/lib.sh"

# ponytail: unico nodo confirmado que corta la carga de verdad en este
# hardware (S2MU005) es batt_slate_mode - store_mode se probo y se queda
# pegado sin aceptar reset por sysfs, descartado. Reanudar puede fallar
# (visto en real: no volvio a cargar solo tras poner slate_mode=0), asi que
# hay reintentos + reboot de ultimo recurso con cooldown para no entrar en
# bucle de reinicios.
# Rango bajado de 75-80% a 45-60% (2026-09-04, investigado con el usuario):
# para un dispositivo siempre enchufado sin uso real, lo que mas degrada la
# bateria es el envejecimiento por calendario (tiempo a alto SOC), no la
# profundidad de descarga - no hay ciclos reales que proteger aqui, asi que
# ensanchar hacia el 20% no ayuda, pero bajar el techo si (BU-808: ~96%
# capacidad retenida al 40% vs ~80% al 100% tras un año a 25°C).
STOP_AT=60
RESUME_AT=45
SLATE=/sys/class/power_supply/battery/batt_slate_mode
STATE_DIR="$HOME_DIR/state"
mkdir -p "$STATE_DIR"
STATE_FILE="$STATE_DIR/charge-limit-state.txt"       # limited | normal
COOLDOWN_FILE="$STATE_DIR/charge-reboot-cooldown.txt"
LOG="$HOME_DIR/charge-control.log"
REBOOT_COOLDOWN=3600
MAX_RETRIES=3

ts() { date '+%Y-%m-%d %H:%M:%S'; }

info=$(termux-battery-status 2>/dev/null)
pct=$(echo "$info" | jq -r '.percentage' 2>/dev/null)
status=$(echo "$info" | jq -r '.status' 2>/dev/null)
plugged=$(echo "$info" | jq -r '.plugged' 2>/dev/null)

if [ -z "$pct" ] || [ "$pct" = "null" ]; then
  echo "$(ts) termux-battery-status sin datos, saltando pasada" >> "$LOG"
  exit 0
fi

state=$(cat "$STATE_FILE" 2>/dev/null || echo normal)

# reconciliacion: si algo externo (p.ej. un reboot, que resetea
# batt_slate_mode a 0 solo) ya devolvio la carga a la normalidad sin
# pasar por este script, corrige el estado guardado en silencio
if [ "$state" = "limited" ] && [ "$status" = "CHARGING" ]; then
  echo "$(ts) estado 'limited' no cuadra con status=CHARGING real, corrigiendo" >> "$LOG"
  state=normal
  echo "normal" > "$STATE_FILE"
fi

if [ "$state" = "normal" ] && [ "$plugged" != "UNPLUGGED" ] && [ "$pct" -ge "$STOP_AT" ] && [ "$status" != "DISCHARGING" ]; then
  su -c "echo 1 > $SLATE" >> "$LOG" 2>&1
  echo "limited" > "$STATE_FILE"
  echo "$(ts) carga cortada al ${pct}%" >> "$LOG"
  send_telegram "Bateria del J5 al ${pct}%: corte la carga automaticamente para no dejarlo al 100% todo el rato. Se reanuda sola al bajar de ${RESUME_AT}%."
  exit 0
fi

if [ "$state" = "limited" ]; then
  should_resume=""
  [ "$pct" -le "$RESUME_AT" ] && should_resume=1
  [ "$plugged" = "UNPLUGGED" ] && should_resume=1
  if [ -n "$should_resume" ]; then
    ok=""
    i=0
    while [ "$i" -lt "$MAX_RETRIES" ]; do
      su -c "echo 0 > $SLATE" >> "$LOG" 2>&1
      sleep 3
      new_status=$(termux-battery-status 2>/dev/null | jq -r '.status' 2>/dev/null)
      if [ "$new_status" = "CHARGING" ] || [ "$new_status" = "FULL" ] || [ "$plugged" = "UNPLUGGED" ]; then
        ok=1
        break
      fi
      i=$((i + 1))
    done
    echo "normal" > "$STATE_FILE"
    if [ -n "$ok" ]; then
      echo "$(ts) carga reanudada al ${pct}% (intento $((i + 1)))" >> "$LOG"
      send_telegram "Bateria del J5 al ${pct}%: carga reanudada."
    else
      now=$(date +%s)
      last_reboot=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
      if [ $((now - last_reboot)) -ge "$REBOOT_COOLDOWN" ]; then
        echo "$now" > "$COOLDOWN_FILE"
        echo "$(ts) no se pudo reanudar carga tras $MAX_RETRIES intentos, reiniciando" >> "$LOG"
        send_telegram "Aviso: el J5 no reanudo la carga tras cortarla al ${STOP_AT}% (probado $MAX_RETRIES veces). Reiniciando el dispositivo automaticamente para forzarlo."
        su -c reboot
      else
        echo "$(ts) no se pudo reanudar carga y reboot en cooldown (ultimo hace $((now - last_reboot))s)" >> "$LOG"
        send_telegram "Aviso: el J5 sigue sin reanudar la carga tras cortarla al ${STOP_AT}%, y ya se reinicio por esto hace poco. Revisalo a mano."
      fi
    fi
  fi
fi
