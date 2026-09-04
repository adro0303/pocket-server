#!/data/data/com.termux/files/usr/bin/bash
HOME_DIR="/data/data/com.termux/files/home"
source "$HOME_DIR/scripts/lib.sh"

STATE_DIR="$HOME_DIR/state"
SEEN_JOBS_FILE="$STATE_DIR/seen-jobs.txt"
PENDING_EMAIL_JOBS_FILE="$STATE_DIR/pending-email-jobs.tsv"
mkdir -p "$STATE_DIR"
touch "$SEEN_JOBS_FILE"

SECTION=""

# 1. Ofertas ya acumuladas desde el correo (LinkedIn, Monster)
if [ -f "$PENDING_EMAIL_JOBS_FILE" ] && [ -s "$PENDING_EMAIL_JOBS_FILE" ]; then
  while IFS=$'\t' read -r position company location link matched source; do
    [ -z "$position" ] && continue
    loc_display="$location"
    [ -z "$loc_display" ] && loc_display="?"
    SECTION="$SECTION
- $position en ${company:-$source} ($loc_display) [$source]
  Coincide en: $matched
  $link
"
  done < "$PENDING_EMAIL_JOBS_FILE"
  > "$PENDING_EMAIL_JOBS_FILE"
fi

# 2. Ofertas nuevas de las fuentes API (RemoteOK, Arbeitnow, Himalayas)
JOBS=$(python3 "$HOME_DIR/scripts/parse_jobs.py" 15)
if [ -n "$JOBS" ]; then
  while IFS=$'\t' read -r position company location link matched source; do
    [ -z "$position" ] && continue
    grep -qxF "$link" "$SEEN_JOBS_FILE" && continue
    echo "$link" >> "$SEEN_JOBS_FILE"
    SECTION="$SECTION
- $position en $company ($location) [$source]
  Coincide en: $matched
  $link
"
  done <<< "$JOBS"
fi

if [ -n "$SECTION" ]; then
  send_telegram "Ofertas de empleo que encajan con tu perfil:
$SECTION" "$BOT_TOKEN_JOBS"
fi
