#!/data/data/com.termux/files/usr/bin/bash
cd /data/data/com.termux/files/home
source scripts/lib.sh
export BOT_TOKEN_PERSONAL CHAT_ID
# ponytail: mata cualquier instancia previa antes de arrancar - dos procesos
# vivos a la vez hacen que Telegram devuelva 409 Conflict en getUpdates para
# ambos, dejando el bot sordo a mensajes reales (incidente 2026-09-04/05)
pkill -f telegram-chat.py 2>/dev/null
sleep 1
nohup python3 scripts/telegram-chat.py > telegram-chat.log 2>&1 &
disown
