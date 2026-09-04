#!/data/data/com.termux/files/usr/bin/bash
HOME_DIR="/data/data/com.termux/files/home"
source "$HOME_DIR/scripts/lib.sh"

HIGH=80
LOW=20
TEMP_HIGH=42
TEMP_RESET=39
STUCK_SECONDS=$((2 * 3600))

STATE_DIR="$HOME_DIR/state"
mkdir -p "$STATE_DIR"
LEVEL_STATE="$STATE_DIR/battery-alert-state.txt"
TEMP_STATE="$STATE_DIR/battery-temp-state.txt"
SINCE_100="$STATE_DIR/battery-100-since.txt"
STUCK_STATE="$STATE_DIR/battery-stuck-state.txt"

last_alert=$(cat "$LEVEL_STATE" 2>/dev/null || echo none)
temp_alert=$(cat "$TEMP_STATE" 2>/dev/null || echo none)
stuck_alert=$(cat "$STUCK_STATE" 2>/dev/null || echo none)

status=$(termux-battery-status)
level=$(echo "$status" | jq -r '.percentage')
plugged=$(echo "$status" | jq -r '.plugged')
temp=$(echo "$status" | jq -r '.temperature')
temp_int=${temp%.*}
now=$(date +%s)

# umbral de reconexion (20%) - el de desconexion al 80% ahora lo gestiona
# charge-control.sh cortando la carga de verdad, ya no hace falta pedirselo
# al usuario
if [ "$plugged" = "UNPLUGGED" ] && [ "$level" -le "$LOW" ] && [ "$last_alert" != "replug_sent" ]; then
  send_telegram "Bateria del J5 al ${level}% y desconectado. Reconectalo antes de que se apague."
  echo "replug_sent" > "$LEVEL_STATE"
elif [ "$plugged" != "UNPLUGGED" ] && [ "$level" -lt "$HIGH" ] && [ "$last_alert" != "none" ]; then
  echo "none" > "$LEVEL_STATE"
fi

# sobrecalentamiento, con histeresis para no repetir en cada pasada
if [ "$temp_int" -ge "$TEMP_HIGH" ] && [ "$temp_alert" != "hot_sent" ]; then
  send_telegram "J5 caliente: ${temp} grados. Revisalo o dale ventilacion."
  echo "hot_sent" > "$TEMP_STATE"
elif [ "$temp_int" -le "$TEMP_RESET" ] && [ "$temp_alert" != "none" ]; then
  echo "none" > "$TEMP_STATE"
fi

# detector de anomalia: si lleva mas de 2h al ~100% enchufado, charge-control.sh
# deberia haberlo cortado mucho antes (STOP_AT=60 desde el 2026-09-04) - si
# esto salta, algo ha fallado en el corte, sea cual sea el umbral configurado
if [ "$plugged" != "UNPLUGGED" ] && [ "$level" -ge 99 ]; then
  since=$(cat "$SINCE_100" 2>/dev/null)
  if [ -z "$since" ]; then
    echo "$now" > "$SINCE_100"
  elif [ $((now - since)) -ge "$STUCK_SECONDS" ] && [ "$stuck_alert" != "stuck_sent" ]; then
    send_telegram "El J5 lleva mas de 2h al ${level}% enchufado y no deberia (charge-control.sh deberia haberlo cortado mucho antes) - revisa charge-control.log, puede haber fallado el corte."
    echo "stuck_sent" > "$STUCK_STATE"
  fi
else
  rm -f "$SINCE_100"
  [ "$stuck_alert" != "none" ] && echo "none" > "$STUCK_STATE"
fi
