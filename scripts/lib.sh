# Rellena esto con tus propias credenciales antes de usarlo - nunca subas
# esta versión rellena a un repo público. Los tokens de bot se crean
# hablando con @BotFather en Telegram; CHAT_ID es el de tu chat privado
# con cada bot (mándale un mensaje y consulta
# https://api.telegram.org/bot<token>/getUpdates para verlo).
API_KEY="elige-una-clave-cualquiera-para-el-servidor-local"
BOT_TOKEN_PERSONAL="TU_TOKEN_DEL_BOT_PERSONAL"
BOT_TOKEN_INVEST="TU_TOKEN_DEL_BOT_DE_INVERSION"
BOT_TOKEN_JOBS="TU_TOKEN_DEL_BOT_DE_EMPLEO"
CHAT_ID="TU_CHAT_ID"
HOME_DIR="/data/data/com.termux/files/home"

QWEN_STARTED=0
QWEN_PID=""

start_qwen() {
  if [ "$QWEN_STARTED" -eq 1 ]; then
    return
  fi
  "$HOME_DIR/llama.cpp/build/bin/llama-server" -m "$HOME_DIR/models/Qwen3-0.6B-Q4_K_M.gguf" --host 127.0.0.1 --port 8082 --api-key "$API_KEY" -c 4096 -t 6 > "$HOME_DIR/qwen-shared.log" 2>&1 &
  QWEN_PID=$!
  for i in $(seq 1 30); do
    if curl -s -m 2 http://127.0.0.1:8082/health | grep -q ok; then
      break
    fi
    sleep 2
  done
  QWEN_STARTED=1
}

stop_qwen() {
  if [ "$QWEN_STARTED" -eq 1 ]; then
    kill "$QWEN_PID" 2>/dev/null
    QWEN_STARTED=0
  fi
}

explain() {
  local prompt="$1"
  local max_tokens="${2:-100}"
  local body
  body=$(jq -n --arg p "$prompt
/no_think" --argjson mt "$max_tokens" '{messages:[{role:"user",content:$p}],max_tokens:$mt}')
  curl -s http://127.0.0.1:8082/v1/chat/completions -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$body" | jq -r 'if (.choices[0].message.content|length)>0 then .choices[0].message.content else "" end'
}

# ponytail: un solo punto de logging (aqui) en vez de instrumentar cada
# script que llama a send_telegram, para que telegram-chat.py pueda
# responder con lo que de verdad se ha mandado (correos, noticias, avisos)
send_telegram() {
  local text="$1"
  local token="${2:-$BOT_TOKEN_PERSONAL}"
  local response
  response=$(curl -s "https://api.telegram.org/bot$token/sendMessage" \
    --data-urlencode "chat_id=$CHAT_ID" \
    --data-urlencode "text=$text")
  if ! echo "$response" | grep -q '"ok":true'; then
    echo "$(date -Iseconds) $response" >> "$HOME_DIR/telegram-errors.log"
    return
  fi
  local bot="personal"
  [ "$token" = "$BOT_TOKEN_INVEST" ] && bot="inversion"
  [ "$token" = "$BOT_TOKEN_JOBS" ] && bot="empleo"
  local mid
  mid=$(echo "$response" | jq -r '.result.message_id // empty')
  mkdir -p "$HOME_DIR/state"
  jq -cn --arg ts "$(date -Iseconds)" --arg bot "$bot" --arg txt "$text" --argjson mid "${mid:-null}" \
    '{ts:$ts, bot:$bot, text:$txt, message_id:$mid}' >> "$HOME_DIR/state/sent-log.jsonl"
}
