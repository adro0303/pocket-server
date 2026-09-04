#!/data/data/com.termux/files/usr/bin/bash
HOME_DIR="/data/data/com.termux/files/home"
source "$HOME_DIR/scripts/lib.sh"

STATE_DIR="$HOME_DIR/state"
mkdir -p "$STATE_DIR"
UID_FILE="$STATE_DIR/last-email-uid.txt"
SEEN_JOBS_FILE="$STATE_DIR/seen-jobs.txt"
PENDING_EMAIL_JOBS_FILE="$STATE_DIR/pending-email-jobs.tsv"
touch "$SEEN_JOBS_FILE"

RESULTS=$(python3 "$HOME_DIR/scripts/imap_watch.py" "$UID_FILE")
[ -z "$RESULTS" ] && exit 0

while IFS=$'\t' read -r type f1 f2 f3 f4 f5; do
  [ -z "$type" ] && continue

  if [ "$type" = "LINKEDIN" ] || [ "$type" = "MONSTER" ]; then
    title="$f1" company="$f2" location="$f3" link="$f4" matched="$f5"
    source_name="LinkedIn"
    [ "$type" = "MONSTER" ] && source_name="Monster"
    [ -z "$link" ] && continue
    grep -qxF "$link" "$SEEN_JOBS_FILE" && continue
    echo "$link" >> "$SEEN_JOBS_FILE"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$title" "$company" "$location" "$link" "$matched" "$source_name" >> "$PENDING_EMAIL_JOBS_FILE"
  else
    sender="$f1" subject="$f2" snippet="$f3" msgid="$f4" from_addr="$f5"
    # ponytail: confirmaciones de candidatura ya enviada (InfoJobs, LinkedIn,
    # ATS de empresas) no son ofertas nuevas ni requieren accion - se
    # descartan antes de llegar al LLM, que las marcaba IMPORTANTE por error
    if printf '%s %s' "$sender" "$subject" | grep -Eiq 'te has inscrito|hemos recibido tu (candidatura|solicitud)|candidatura (recibida|enviada)|solicitud (recibida|enviada)|tu candidatura ha sido|application (has been )?(received|submitted)|thank you for (applying|your application)|hemos recibido tu aplicacion'; then
      continue
    fi
    # ponytail: keyword pre-filter en vez de pedirle al LLM de 0.6B una
    # distincion de 3 vias que en pruebas reales no acertaba de forma fiable
    if printf '%s %s' "$sender" "$subject" | grep -Eiq 'recruit|candidate experience|job opportunit|talent acquisition|career (site|portal)|vacante|oferta de empleo'; then
      start_qwen
      translated=$(explain "Traduce este texto al espanol de forma natural, sin comentarios ni notas aparte, responde solo con la traduccion: $snippet" 200)
      [ -z "$translated" ] && translated="$snippet"
      send_telegram "Notificacion de empleo:
De: $sender
Asunto: $subject

$translated" "$BOT_TOKEN_JOBS"
      continue
    fi
    start_qwen
    verdict=$(explain "Clasifica este correo como IMPORTANTE o RUTINA. IMPORTANTE si requiere accion pronto, es de un banco, una administracion, una entrevista de trabajo o algo urgente. RUTINA si es publicidad, notificaciones automaticas o boletines. Responde SOLO con una palabra: IMPORTANTE o RUTINA. Remitente: $sender. Asunto: $subject. Contenido: $snippet" 10)
    if echo "$verdict" | grep -qi "IMPORTANTE"; then
      send_telegram "Correo importante:
De: $sender
Asunto: $subject

$snippet"
      # ponytail: guarda a que correo real corresponde este aviso (mid de
      # Telegram -> from/asunto/Message-ID) para que telegram-chat.py pueda
      # responderlo de verdad si el usuario contesta a este mensaje
      if [ -n "$from_addr" ]; then
        tg_mid=$(tail -1 "$STATE_DIR/sent-log.jsonl" | jq -r '.message_id // empty')
        if [ -n "$tg_mid" ]; then
          jq -cn --argjson tg_mid "$tg_mid" --arg from "$from_addr" --arg subject "$subject" --arg msgid "$msgid" \
            '{tg_message_id:$tg_mid, from:$from, subject:$subject, message_id_header:$msgid}' >> "$STATE_DIR/email-refs.jsonl"
        fi
      fi
    fi
  fi
done <<< "$RESULTS"

stop_qwen
