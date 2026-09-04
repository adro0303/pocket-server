#!/data/data/com.termux/files/usr/bin/bash
HOME_DIR="/data/data/com.termux/files/home"
source "$HOME_DIR/scripts/lib.sh"

STATE_DIR="$HOME_DIR/state"
SEEN_FILE="$STATE_DIR/seen-invest.txt"
PENDING_FILE="$STATE_DIR/pending-invest.tsv"
LAST_DIGEST_FILE="$STATE_DIR/last-digest.txt"
PRICE_REF_FILE="$STATE_DIR/price-ref.txt"

DIGEST_INTERVAL_SECONDS=$((4 * 3600))
PRICE_WINDOW_SECONDS=$((2 * 3600))
BTC_THRESHOLD=3
GOLD_THRESHOLD=1.5

mkdir -p "$STATE_DIR"

# feed_url|categoria
FEEDS="https://www.coindesk.com/arc/outboundfeeds/rss/|Bitcoin/Cripto
https://www.investing.com/rss/commodities_Metals.rss|Oro/Metales
https://www.investing.com/rss/news_285.rss|Tipos de interes/Mercados"

RELEVANT_RE="gold|oro|bitcoin|btc|crypto|fed |federal reserve|interest rate|tipos de interes|rate hike|rate cut|powell|ecb|bce |bond yield|treasury yield|inflation|inflacion|recession"
IMPORTANT_RE="rate cut|rate hike|recession|crash|surge|record high|war|sanctions|emergency|ban |halving|default|plunge|soar"

URGENT_MSG=""

invest_explain() {
  explain "Explica en una frase corta en espanol si esta noticia probablemente hace SUBIR o BAJAR el precio del oro, del bitcoin, o los tipos de interes. Empieza la frase con 'Sube' o 'Baja' (o 'Sin efecto claro' si no se puede saber la direccion), y luego explica por que. No inventes datos que no esten en el titular. Titular: $1" 100
}

# --- 1. Comprobacion de movimientos de precio anomalos ---
check_price() {
  local name="$1" api_url="$2" jq_filter="$3" threshold="$4"
  local cur
  cur=$(curl -s -m 8 "$api_url" | jq -r "$jq_filter")
  [ -z "$cur" ] || [ "$cur" = "null" ] && return

  local ref_line
  ref_line=$(grep "^$name " "$PRICE_REF_FILE" 2>/dev/null)
  if [ -z "$ref_line" ]; then
    echo "$name $cur $(date +%s)" >> "$PRICE_REF_FILE"
    return
  fi

  local ref_price ref_time
  ref_price=$(echo "$ref_line" | awk '{print $2}')
  ref_time=$(echo "$ref_line" | awk '{print $3}')

  local result alert refresh pct
  result=$(python3 "$HOME_DIR/scripts/check_move.py" "$cur" "$ref_price" "$ref_time" "$threshold" "$PRICE_WINDOW_SECONDS")
  alert=$(echo "$result" | cut -f1)
  refresh=$(echo "$result" | cut -f2)
  pct=$(echo "$result" | cut -f3)

  if [ "$alert" = "1" ]; then
    URGENT_MSG="$URGENT_MSG
[$name] AVISO - movimiento anomalo: $pct% en las ultimas ~2h (precio actual: $cur)"
  fi

  if [ "$refresh" = "1" ]; then
    sed -i "/^$name /d" "$PRICE_REF_FILE"
    echo "$name $cur $(date +%s)" >> "$PRICE_REF_FILE"
  fi
}

check_price "btc" "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" ".bitcoin.usd" "$BTC_THRESHOLD"
check_price "gold" "https://api.gold-api.com/price/XAU" ".price" "$GOLD_THRESHOLD"

# --- 2. Noticias nuevas relevantes ---
ALL_ITEMS=""
while IFS='|' read -r feed category; do
  [ -z "$feed" ] && continue
  ITEMS=$(python3 "$HOME_DIR/scripts/parse_feed.py" "$feed" 15)
  while IFS=$'\t' read -r title link; do
    [ -z "$title" ] && continue
    ALL_ITEMS="$ALL_ITEMS$title"$'\t'"$link"$'\t'"$category"$'\n'
  done <<< "$ITEMS"
done <<< "$FEEDS"

FIRST_RUN=0
if [ ! -f "$SEEN_FILE" ]; then
  FIRST_RUN=1
  touch "$SEEN_FILE"
fi

while IFS=$'\t' read -r title link category; do
  [ -z "$link" ] && continue
  if grep -qxF "$link" "$SEEN_FILE"; then
    continue
  fi
  echo "$link" >> "$SEEN_FILE"
  [ "$FIRST_RUN" -eq 1 ] && continue
  echo "$title" | grep -qiE "$RELEVANT_RE" || continue

  if echo "$title" | grep -qiE "$IMPORTANT_RE"; then
    start_qwen
    EXPLANATION=$(invest_explain "$title")
    URGENT_MSG="$URGENT_MSG

[$category] IMPORTANTE: $title
  → $EXPLANATION
$link"
  else
    printf '%s\t%s\t%s\n' "$title" "$link" "$category" >> "$PENDING_FILE"
  fi
done <<< "$ALL_ITEMS"

# --- 3. Aviso inmediato si hay algo urgente (precio o noticia gorda) ---
if [ -n "$URGENT_MSG" ]; then
  send_telegram "AVISO URGENTE - inversiones
$URGENT_MSG" "$BOT_TOKEN_INVEST"
fi

# --- 4. Resumen periodico de lo acumulado ---
LAST_DIGEST=0
[ -f "$LAST_DIGEST_FILE" ] && LAST_DIGEST=$(cat "$LAST_DIGEST_FILE")
NOW=$(date +%s)

if [ -f "$PENDING_FILE" ] && [ -s "$PENDING_FILE" ] && [ $((NOW - LAST_DIGEST)) -ge "$DIGEST_INTERVAL_SECONDS" ]; then
  start_qwen
  DIGEST=""
  while IFS=$'\t' read -r title link category; do
    [ -z "$title" ] && continue
    EXPLANATION=$(invest_explain "$title")
    DIGEST="$DIGEST
[$category] $title
  → $EXPLANATION
$link
"
  done < "$PENDING_FILE"
  send_telegram "Resumen de inversiones (ultimas horas):
$DIGEST" "$BOT_TOKEN_INVEST"
  > "$PENDING_FILE"
  echo "$NOW" > "$LAST_DIGEST_FILE"
fi

stop_qwen
