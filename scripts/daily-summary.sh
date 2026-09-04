#!/data/data/com.termux/files/usr/bin/bash
HOME_DIR="/data/data/com.termux/files/home"
source "$HOME_DIR/scripts/lib.sh"

digest_section() {
  local label="$1" feed="$2" limit="$3" token="${4:-$BOT_TOKEN_PERSONAL}" tweet="${5:-0}"
  local items
  items=$(python3 "$HOME_DIR/scripts/parse_feed.py" "$feed" "$limit")
  [ -z "$items" ] && return

  start_qwen
  local section="
=== $label ==="
  local tweet_tsv=""
  while IFS=$'\t' read -r title link; do
    [ -z "$title" ] && continue
    local exp
    exp=$(explain "Explica en una frase corta y neutra en espanol de que trata esta noticia, basandote solo en el titular. No inventes datos ni repitas el titular. Titular: $title" 80)
    section="$section
- $title
  → $exp
$link
"
    tweet_tsv="$tweet_tsv$title	$exp	$link
"
  done <<< "$items"
  send_telegram "$section" "$token"
  # ponytail: reusa el mismo $exp ya calculado para Telegram en vez de
  # pedirle al LLM una segunda redaccion solo para el tweet
  if [ "$tweet" = "1" ]; then
    tweet_out=$(printf '%s' "$tweet_tsv" | python3 "$HOME_DIR/scripts/twitter.py" digest "Resumen $label:" 2>&1)
    echo "$(date '+%Y-%m-%d %H:%M:%S') hilo de twitter ($label): $tweet_out" >> "$HOME_DIR/daily-summary.log"
  fi
}

digest_section "Tech (Hacker News)" "https://hnrss.org/frontpage" 6 "" 1
digest_section "Inteligencia Artificial" "https://hnrss.org/newest?q=AI+OR+LLM" 6 "" 1
digest_section "Geopolitica" "https://feeds.bbci.co.uk/news/world/rss.xml" 6 "$BOT_TOKEN_INVEST"

stop_qwen
