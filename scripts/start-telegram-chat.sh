#!/data/data/com.termux/files/usr/bin/bash
cd /data/data/com.termux/files/home
source scripts/lib.sh
export BOT_TOKEN_PERSONAL CHAT_ID
nohup python3 scripts/telegram-chat.py > telegram-chat.log 2>&1 &
disown
