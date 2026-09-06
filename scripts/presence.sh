#!/data/data/com.termux/files/usr/bin/bash
HOME_DIR="/data/data/com.termux/files/home"
source "$HOME_DIR/scripts/lib.sh"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# ponytail: MAC del Wi-Fi del iPhone, unico identificador estable para
# detectar presencia por ARP (la IP cambia por DHCP, la MAC no).
IPHONE_MAC="AA:BB:CC:DD:EE:FF"  # Ajustes > General > Informacion > Direccion Wi-Fi (iOS)

STATE_DIR="$HOME_DIR/state"
mkdir -p "$STATE_DIR"
STATE_FILE="$STATE_DIR/presence-state.txt"     # "confirmado pendiente contador"
OVERRIDE_FILE="$STATE_DIR/presence-override.txt"
LOG="$HOME_DIR/presence.log"
LUCES="$HOME_DIR/scripts/luces.py"
PY="/data/data/com.termux/files/usr/bin/python3"
SUBNET="192.168.1"

# ponytail: una desconexion real de wifi (usuario la quita y la pone) o el
# movil quedandose sin bateria son indistinguibles de "salio de casa" en una
# sola lectura - exigir varias lecturas seguidas de "away" antes de dar la
# salida por buena absorbe esos casos cortos (una desconexion de wifi de 1-2
# min no aguanta 3 pasadas de 5 min = 15 min). No soluciona el caso de
# bateria muerta durante HORAS estando en casa - eso no se puede distinguir
# de una salida real solo con presencia por ARP - para eso esta el
# OVERRIDE_FILE de abajo (interruptor manual, no detectado solo).
THRESH_AWAY=3
THRESH_HOME=1

# ponytail: valvula de escape manual para el caso que el debounce no cubre
# (bateria muerta durante horas estando en casa). Vacio/ausente = automatico.
# Para forzar "estoy en casa pase lo que pase": echo home > presence-override.txt
# Quitar el fichero (o dejarlo vacio) para volver a automatico.
override=""
[ -f "$OVERRIDE_FILE" ] && override=$(tr -d '[:space:]' < "$OVERRIDE_FILE")

# ponytail: /proc/net/arp necesita root en este Android (confirmado: falla
# con Permission denied para el usuario normal de Termux). El ping sweep en
# si no lo necesita, pero como hay que leer el arp de todas formas, todo el
# bloque va por su -c para no abrir dos rutas de permisos distintas.
detected=$(su -c "
  for i in \$(seq 1 254); do ping -c1 -W1 ${SUBNET}.\$i >/dev/null 2>&1 & done
  wait
  grep -qi '$IPHONE_MAC' /proc/net/arp && echo home || echo away
")

if [ "$override" = "home" ] || [ "$override" = "away" ]; then
  echo "$(ts) override manual activo ($override), ignorando lectura real ($detected)" >> "$LOG"
  detected="$override"
fi

if [ -f "$STATE_FILE" ]; then
  read -r confirmed pending count < "$STATE_FILE"
else
  confirmed="unknown"; pending=""; count=0
fi

if [ "$confirmed" = "unknown" ]; then
  echo "$detected $detected 0" > "$STATE_FILE"
  echo "$(ts) primera pasada, estado inicial: $detected" >> "$LOG"
  exit 0
fi

if [ "$detected" = "$confirmed" ]; then
  echo "$confirmed $confirmed 0" > "$STATE_FILE"
  exit 0
fi

if [ "$pending" = "$detected" ]; then
  count=$((count + 1))
else
  pending="$detected"
  count=1
fi

threshold=$THRESH_HOME
[ "$detected" = "away" ] && threshold=$THRESH_AWAY

if [ "$count" -lt "$threshold" ]; then
  echo "$confirmed $pending $count" > "$STATE_FILE"
  echo "$(ts) posible cambio a $detected ($count/$threshold), sin actuar todavia" >> "$LOG"
  exit 0
fi

prev="$confirmed"
confirmed="$detected"
echo "$confirmed $confirmed 0" > "$STATE_FILE"

if [ "$prev" = "away" ] && [ "$confirmed" = "home" ]; then
  now_min=$(( $(date +%H) * 60 + $(date +%M) ))
  if [ "$now_min" -ge $((21*60)) ] && [ "$now_min" -lt $((23*60+30)) ]; then
    echo "$(ts) llegada confirmada (noche temprana), encendiendo entrada+salon marron 40%" >> "$LOG"
    "$PY" "$LUCES" entrada brown 40 >> "$LOG" 2>&1
    "$PY" "$LUCES" "Luz salon" brown 40 >> "$LOG" 2>&1
    send_telegram "Llegada detectada: entrada y salon encendidas (marron, 40%)."
  elif [ "$now_min" -ge $((23*60+30)) ] || [ "$now_min" -lt $((6*60)) ]; then
    echo "$(ts) llegada confirmada (tarde), encendiendo entrada+pasillo marron sin tocar intensidad" >> "$LOG"
    "$PY" "$LUCES" entrada brown >> "$LOG" 2>&1
    "$PY" "$LUCES" Pasillo brown >> "$LOG" 2>&1
    send_telegram "Llegada detectada (tarde): entrada y pasillo encendidas (marron)."
  else
    echo "$(ts) llegada confirmada de dia, no se toca nada" >> "$LOG"
  fi
elif [ "$prev" = "home" ] && [ "$confirmed" = "away" ]; then
  echo "$(ts) salida confirmada tras $THRESH_AWAY lecturas seguidas, apagando todas las luces" >> "$LOG"
  "$PY" "$LUCES" todas off >> "$LOG" 2>&1
  send_telegram "Salida detectada: todas las luces apagadas por si acaso."
fi
