#!/data/data/com.termux/files/usr/bin/python3
"""Poller de Telegram: contesta preguntas mandadas al bot personal usando
Qwen3 (via explain() de lib.sh), con datos reales del dispositivo inyectados
en el prompt para que no invente cosas sobre si mismo."""
import json
import os
import re
import smtplib
import socket
import subprocess
import threading
import time
import urllib.request
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

TOKEN = os.environ["BOT_TOKEN_PERSONAL"]
CHAT_ID = os.environ["CHAT_ID"]
HOME = "/data/data/com.termux/files/home"
STATE_FILE = os.path.expanduser("~/state/telegram-chat-offset.txt")
API_BASE = f"https://api.telegram.org/bot{TOKEN}"

# ponytail: comando reconocido por patron fijo antes de llegar al LLM (igual
# que el filtro de empleo/RRHH en email-watch.sh) - el LLM no decide cuando
# se manda el magic packet, solo esta frase exacta lo hace
WAKE_RE = re.compile(
    r"^/?(wake|despertar)\b|enc(?:e|ie|ié)nd\w*\s+(el\s+)?(pc|portatil|portátil|ordenador|laptop)",
    re.IGNORECASE,
)

# ponytail: apagar es irreversible en caliente (perdida de trabajo sin
# guardar), asi que a diferencia de WAKE_RE no basta con el patron fijo -
# hace falta una confirmacion explicita en un mensaje aparte antes de
# ejecutar. El SSH usa una clave dedicada con "command=" forzado en el
# portatil (solo puede correr sudo poweroff, nada mas) y sudoers con
# NOPASSWD solo para ese comando exacto - ni el LLM ni un mensaje suelto
# tienen permiso real de apagar nada por si solos.
SHUTDOWN_RE = re.compile(
    r"^/?(apagar|apaga|shutdown|poweroff)\b|ap[aá]g\w*\s+(el\s+)?(pc|portatil|portátil|ordenador|laptop)",
    re.IGNORECASE,
)
CONFIRM_RE = re.compile(r"^\s*confirmar\.?\s*$", re.IGNORECASE)
LAPTOP_IP = "100.x.x.x"  # IP Tailscale de tu portatil (tailscale ip -4 en el portatil)
LAPTOP_USER = "tu_usuario"
SHUTDOWN_KEY = os.path.join(HOME, ".ssh", "laptop_shutdown")
CONFIRM_STATE = os.path.join(HOME, "state", "shutdown-confirm.txt")
# ponytail: 60s se quedaba corto en real - entre el retraso de la
# notificacion de Telegram y escribir CONFIRMAR a mano, el "CONFIRMAR" del
# usuario llegaba pasada la ventana y caia en silencio al asistente
# generico (contesto sobre bateria en vez de apagar). Ampliado a 120s.
CONFIRM_WINDOW_SECONDS = 120


# ponytail: encender/apagar una luz es reversible e inmediato, igual que el
# magic packet de WAKE_RE - no hace falta el patron de borrador+CONFIRMAR
# que usan correo/tweet (eso es para lo irreversible o visible a terceros).
LUCES_SCRIPT = os.path.join(HOME, "scripts", "luces.py")
LUCES_ALIASES = {
    "despacho": "Luz despacho",
    "salon": "Luz salon",
    "salón": "Luz salon",
    "pasillo": "Pasillo",
    "espejo": "Espejo",
    "zapatero": "Zapatero",
    "entrada": "entrada",
    "todas": "todas",
}
LUCES_COMMAND_RE = re.compile(
    r"^/?luces\s+(?P<target>\S+)\s+(?P<action>on|off|encender|apagar)\s*$",
    re.IGNORECASE,
)
LUCES_NATURAL_RE = re.compile(
    r"\b(?P<verb>enc(?:e|ie|ié)nd\w*|prend\w*|apag\w*)\b.{0,30}?"
    r"\b(?P<target>despacho|sal[oó]n|pasillo|espejo|zapatero|entrada|todas)\b",
    re.IGNORECASE | re.DOTALL,
)


def parse_luces(text):
    m = LUCES_COMMAND_RE.match(text)
    if m:
        action = "on" if m.group("action").lower() in ("on", "encender") else "off"
        return m.group("target"), action
    m = LUCES_NATURAL_RE.search(text)
    if m:
        action = "off" if m.group("verb").lower().startswith("apag") else "on"
        return m.group("target"), action
    return None


def run_luces(target_key, action):
    target = LUCES_ALIASES.get(target_key.lower(), target_key)
    result = subprocess.run(
        ["python3", LUCES_SCRIPT, target, action],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode == 0:
        return result.stdout.strip() or f"{target}: {action}"
    err = (result.stderr or result.stdout).strip()
    return f"No se pudo controlar '{target}': {err[:200]}"


def send_wake_packet():
    result = subprocess.run(
        ["python3", os.path.join(HOME, "wake.py")],
        capture_output=True, text=True, timeout=15,
    )
    out = (result.stdout or result.stderr).strip()
    return out if out else "Magic packet enviado."


def request_shutdown_confirm():
    os.makedirs(os.path.dirname(CONFIRM_STATE), exist_ok=True)
    with open(CONFIRM_STATE, "w") as f:
        f.write(str(time.time()))
    return (
        "Vas a apagar el portatil. Contesta CONFIRMAR (solo esa palabra) "
        f"en el proximo minuto para hacerlo de verdad."
    )


def _shutdown_confirm_age():
    try:
        with open(CONFIRM_STATE) as f:
            return time.time() - float(f.read().strip())
    except Exception:
        return None


def shutdown_confirm_pending():
    age = _shutdown_confirm_age()
    return age is not None and age <= CONFIRM_WINDOW_SECONDS


def shutdown_confirm_expired():
    age = _shutdown_confirm_age()
    return age is not None and age > CONFIRM_WINDOW_SECONDS


def clear_shutdown_confirm():
    try:
        os.remove(CONFIRM_STATE)
    except Exception:
        pass


def send_shutdown_signal():
    result = subprocess.run(
        ["ssh", "-i", SHUTDOWN_KEY, "-o", "StrictHostKeyChecking=accept-new",
         "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
         f"{LAPTOP_USER}@{LAPTOP_IP}", "shutdown-request"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        return "Orden de apagado enviada al portatil."
    err = (result.stderr or result.stdout).strip()
    return f"No se pudo conectar por SSH (codigo {result.returncode}): {err[:200]}"


def laptop_reachable(timeout=5):
    try:
        with socket.create_connection((LAPTOP_IP, 22), timeout=timeout):
            return True
    except OSError:
        return False


def notify_shutdown_result():
    # ponytail: unico rastro real disponible de que el poweroff surtio
    # efecto sin tocar el comando forzado del portatil (sigue restringido
    # a "sudo poweroff", nada mas) - si deja de responder por SSH, se apago.
    time.sleep(20)
    text = (
        "El portatil ya no responde por SSH: se ha apagado."
        if not laptop_reachable()
        else "El portatil sigue respondiendo por SSH pasados 20s, puede que no se haya apagado - revisalo."
    )
    try:
        api_call("sendMessage", {"chat_id": CHAT_ID, "text": text})
    except Exception:
        pass


# ponytail: mandar/responder un correo es visible para un tercero y no se
# puede deshacer, igual de irreversible que apagar el portatil - mismo
# patron de confirmacion (CONFIRM_RE ya declarado arriba se reutiliza). La
# diferencia pedida por el usuario: en vez de solo "confirmar o nada",
# tambien puede reenviar el borrador reescrito (Para:/Asunto:/cuerpo) para
# mandarlo YA con los cambios, sin repetir /enviar ni una segunda espera.
EMAIL_USER = "tu_correo@gmail.com"
EMAIL_DRAFT_STATE = os.path.join(HOME, "state", "email-draft.json")
EMAIL_REFS_FILE = os.path.join(HOME, "state", "email-refs.jsonl")
EMAIL_CONFIRM_WINDOW_SECONDS = 180
DRAFT_BODY_RE = re.compile(
    r"^\s*para\s*:\s*(?P<to>\S+@\S+?)\s*\n\s*asunto\s*:\s*(?P<subject>[^\n]*)\n{1,2}(?P<body>.*)$",
    re.IGNORECASE | re.DOTALL,
)

# ponytail: para "manda un correo a X diciendo Y" en lenguaje natural, el
# LLM SOLO redacta el cuerpo/asunto (texto libre, no hay nada peligroso en
# que se equivoque redactando) - nunca decide el destinatario (se exige
# una direccion real escrita por el usuario, extraida con regex, no
# inventada por el modelo) ni el envio (pasa por el mismo borrador con
# CONFIRMAR/reescritura que ya usan /enviar y responder).
NATURAL_SEND_RE = re.compile(
    r"\b(m[aá]nd\w*|env[ií]\w*|escrib\w*)\b.{0,40}\b(correo|email|mensaje)\b",
    re.IGNORECASE | re.DOTALL,
)
EMAIL_ADDR_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def parse_natural_send(text):
    if not NATURAL_SEND_RE.search(text):
        return None
    m = EMAIL_ADDR_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip(".,;")


def parse_draft_text(text, require_command=False):
    stripped = text.strip("\n")
    lines = stripped.split("\n")
    has_command = bool(lines) and re.match(r"^/?enviar\b", lines[0].strip(), re.IGNORECASE)
    if has_command:
        stripped = "\n".join(lines[1:]).strip("\n")
    elif require_command:
        return None
    m = DRAFT_BODY_RE.match(stripped)
    if not m:
        return None
    to = m.group("to").strip().rstrip(".,;")
    subject = m.group("subject").strip()
    body = m.group("body").strip()
    if not to or not subject or not body:
        return None
    return {"to": to, "subject": subject, "body": body}


def format_draft(d):
    return f"Para: {d['to']}\nAsunto: {d['subject']}\n\n{d['body']}"


def draft_prompt(d):
    return (
        "Borrador:\n\n" + format_draft(d) +
        "\n\nContesta CONFIRMAR para mandarlo tal cual, o mandamelo reescrito "
        "con el mismo formato (Para:/Asunto:/cuerpo) para mandar la version "
        "nueva directamente."
    )


def save_email_draft(draft):
    draft = dict(draft)
    draft["ts"] = time.time()
    os.makedirs(os.path.dirname(EMAIL_DRAFT_STATE), exist_ok=True)
    with open(EMAIL_DRAFT_STATE, "w") as f:
        json.dump(draft, f)


def load_email_draft():
    try:
        with open(EMAIL_DRAFT_STATE) as f:
            d = json.load(f)
    except Exception:
        return None
    if time.time() - d.get("ts", 0) > EMAIL_CONFIRM_WINDOW_SECONDS:
        return None
    return d


def clear_email_draft():
    try:
        os.remove(EMAIL_DRAFT_STATE)
    except Exception:
        pass


def find_email_ref(tg_message_id):
    if not tg_message_id:
        return None
    try:
        with open(EMAIL_REFS_FILE) as f:
            lines = f.readlines()
    except Exception:
        return None
    for line in reversed(lines[-200:]):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("tg_message_id") == tg_message_id:
            return e
    return None


def send_email(to, subject, body, in_reply_to=None):
    msg = MIMEText(body, _charset="utf-8")
    msg["From"] = EMAIL_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    try:
        with open(os.path.expanduser("~/.imap_pass")) as f:
            smtp_pass = f.read().strip()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
            s.starttls()
            s.login(EMAIL_USER, smtp_pass)
            s.sendmail(EMAIL_USER, [to], msg.as_string())
        return f"Correo enviado a {to}."
    except Exception as e:
        return f"Fallo al mandar el correo: {e}"


# ponytail: publicar un tweet es igual de visible/irreversible que mandar
# un correo - mismo patron de confirmacion (CONFIRM_RE reutilizado). Mas
# simple que el borrador de correo (solo texto, sin Para:/Asunto:), asi
# que aqui no hay "reescribe y reenvia para mandarlo ya" - para cambiar el
# texto, se repite el comando (crea un borrador nuevo) y se confirma otra
# vez; evita la ambiguedad de no tener un marcador de formato claro como
# Para:/Asunto: para distinguir "esto es una edicion" de "esto es una
# pregunta normal".
TWITTER_SCRIPT = os.path.join(HOME, "scripts", "twitter.py")
TWEET_STATE = os.path.join(HOME, "state", "tweet-draft.json")
TWEET_CONFIRM_WINDOW_SECONDS = 180
TWEET_COMMAND_RE = re.compile(r"^/?twittear\s+(?P<text>.+)$", re.IGNORECASE | re.DOTALL)
TWEET_NATURAL_RE = re.compile(r"\b(tuit\w*|twitte\w*|tweete\w*)\b", re.IGNORECASE)


def save_tweet_draft(text):
    os.makedirs(os.path.dirname(TWEET_STATE), exist_ok=True)
    with open(TWEET_STATE, "w") as f:
        json.dump({"text": text, "ts": time.time()}, f)


def load_tweet_draft():
    try:
        with open(TWEET_STATE) as f:
            d = json.load(f)
    except Exception:
        return None
    if time.time() - d.get("ts", 0) > TWEET_CONFIRM_WINDOW_SECONDS:
        return None
    return d


def clear_tweet_draft():
    try:
        os.remove(TWEET_STATE)
    except Exception:
        pass


def generate_tweet_text(instruction):
    prompt = (
        f"Quiero publicar un tweet a partir de esta idea: {instruction}\n"
        "Responde SOLO con el texto del tweet, sin comillas ni comentarios "
        "aparte, en espanol, natural, maximo 260 caracteres. No inventes "
        "datos que no esten en la idea original."
    )
    script = 'source scripts/lib.sh; start_qwen 1>&2; explain "$1" 150; stop_qwen 1>&2'
    result = subprocess.run(
        ["bash", "-c", script, "_", prompt],
        cwd=HOME, capture_output=True, text=True, timeout=180,
    )
    text = result.stdout.strip().strip('"')
    return text[:280]


def tweet_prompt(text):
    return (
        f"Borrador de tweet:\n\n{text}\n\nContesta CONFIRMAR para publicarlo. "
        "Para cambiarlo, vuelve a pedirlo con el texto nuevo."
    )


def send_tweet(text):
    result = subprocess.run(
        ["python3", TWITTER_SCRIPT, "tweet", text],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode == 0:
        return f"Tweet publicado (id {result.stdout.strip()})."
    err = (result.stderr or result.stdout).strip()
    return f"Fallo al publicar el tweet: {err[:200]}"


def get_offset():
    try:
        with open(STATE_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_offset(offset):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        f.write(str(offset))


def api_call(method, payload, timeout=30):
    req = urllib.request.Request(
        f"{API_BASE}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def recent_sent(hours=24, limit=10):
    path = os.path.join(HOME, "state", "sent-log.jsonl")
    try:
        with open(path) as f:
            lines = f.readlines()
    except Exception:
        return []
    cutoff = time.time() - hours * 3600
    entries = []
    for line in lines[-300:]:
        try:
            e = json.loads(line)
            ts = time.mktime(time.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        if ts >= cutoff:
            entries.append(e)
    return entries[-limit:]


def device_context():
    parts = []
    try:
        bat = json.loads(subprocess.run(
            ["termux-battery-status"], capture_output=True, text=True, timeout=10
        ).stdout)
        plugged = "cargando" if bat["plugged"] != "UNPLUGGED" else "desconectado"
        parts.append(f"Bateria: {bat['percentage']}%, {plugged}, {bat['temperature']} grados")
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        parts.append(f"lleva encendido {secs/3600:.1f} horas")
    except Exception:
        pass
    try:
        with open("/proc/net/dev") as f:
            tun0 = any(line.strip().startswith("tun0:") for line in f)
        parts.append(f"Tailscale {'conectado' if tun0 else 'caido'}")
    except Exception:
        pass
    try:
        sent = recent_sent()
        if sent:
            resumen = []
            for e in sent:
                primera = (e.get("text") or "").strip().splitlines()
                primera = primera[0][:80] if primera else ""
                resumen.append(f"[{e['ts'][11:16]}] ({e.get('bot','?')}) {primera}")
            parts.append("Mensajes enviados en las ultimas 24h: " + " | ".join(resumen))
        else:
            parts.append("No se ha enviado ningun correo/noticia/aviso en las ultimas 24h")
    except Exception:
        pass
    return ". ".join(parts)


def generate_email_draft(to, instruction):
    prompt = (
        f"Quiero mandar un correo a partir de esta idea: {instruction}\n"
        "Responde EXACTAMENTE en este formato, nada de comentarios aparte:\n"
        "Asunto: <asunto corto>\n\n<cuerpo del correo en espanol, natural y breve, "
        "desarrollando la idea. No inventes datos, nombres ni hechos que no esten "
        "en la idea original.>"
    )
    script = 'source scripts/lib.sh; start_qwen 1>&2; explain "$1" 400; stop_qwen 1>&2'
    result = subprocess.run(
        ["bash", "-c", script, "_", prompt],
        cwd=HOME, capture_output=True, text=True, timeout=180,
    )
    raw = result.stdout.strip()
    parsed = parse_draft_text(f"Para: {to}\n{raw}", require_command=False)
    if parsed:
        return parsed["subject"], parsed["body"]
    # ponytail: el modelo de 0.6B no siempre sigue el formato pedido - si no
    # parsea, se usa el texto tal cual como cuerpo en vez de fallar, con un
    # asunto generico sacado de la propia instruccion
    fallback_subject = instruction.strip()[:60] or "Mensaje"
    return fallback_subject, (raw or instruction)


def ask_llm(question):
    context = device_context()
    prompt = (
        f"Datos reales de este movil ahora mismo: {context}. "
        f"Si la pregunta es sobre el propio movil (bateria, temperatura, conexion) o "
        f"sobre correos/noticias/avisos recientes, usa exactamente estos datos, no "
        f"inventes otros ni otros mensajes que no esten aqui. Responde breve. "
        f"Pregunta: {question}"
    )
    script = 'source scripts/lib.sh; start_qwen 1>&2; explain "$1" 300; stop_qwen 1>&2'
    result = subprocess.run(
        ["bash", "-c", script, "_", prompt],
        cwd=HOME, capture_output=True, text=True, timeout=180,
    )
    answer = result.stdout.strip()
    return answer if answer else "No he podido generar respuesta."


def main():
    offset = get_offset()
    print(f"telegram-chat arrancado, offset={offset}", flush=True)
    while True:
        try:
            result = api_call("getUpdates", {"offset": offset, "timeout": 25})
        except Exception as e:
            print(f"getUpdates error: {e}", flush=True)
            time.sleep(5)
            continue
        for update in result.get("result", []):
            offset = update["update_id"] + 1
            save_offset(offset)
            msg = update.get("message") or {}
            text = msg.get("text")
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if not text or chat_id != str(CHAT_ID):
                continue
            print(f"pregunta recibida: {text}", flush=True)
            if CONFIRM_RE.match(text) and shutdown_confirm_pending():
                clear_shutdown_confirm()
                try:
                    answer = send_shutdown_signal()
                except Exception as e:
                    answer = f"Error al apagar: {e}"
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                    print(f"shutdown ejecutado: {answer[:80]}", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                if answer.startswith("Orden de apagado enviada"):
                    threading.Thread(target=notify_shutdown_result, daemon=True).start()
                continue
            if CONFIRM_RE.match(text) and shutdown_confirm_expired():
                clear_shutdown_confirm()
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": "La confirmacion de apagado caduco, no se hizo nada. Vuelve a pedir que apague si quieres hacerlo de verdad."})
                    print("shutdown confirm caducado", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            if SHUTDOWN_RE.search(text):
                answer = request_shutdown_confirm()
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                    print("shutdown pedido, esperando CONFIRMAR", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            draft = load_email_draft()
            if draft:
                sent_answer = None
                if CONFIRM_RE.match(text):
                    clear_email_draft()
                    sent_answer = send_email(draft["to"], draft["subject"], draft["body"], draft.get("in_reply_to"))
                else:
                    edited = parse_draft_text(text, require_command=False)
                    if edited:
                        in_reply_to = draft.get("in_reply_to") if edited["to"] == draft["to"] else None
                        clear_email_draft()
                        sent_answer = send_email(edited["to"], edited["subject"], edited["body"], in_reply_to)
                if sent_answer is not None:
                    try:
                        api_call("sendMessage", {"chat_id": CHAT_ID, "text": sent_answer})
                        print(f"email: {sent_answer[:80]}", flush=True)
                    except Exception as e:
                        print(f"sendMessage error: {e}", flush=True)
                    continue
            reply_to = msg.get("reply_to_message") or {}
            ref = find_email_ref(reply_to.get("message_id"))
            if ref:
                subject = ref.get("subject") or "(sin asunto)"
                if not subject.lower().startswith("re:"):
                    subject = "Re: " + subject
                new_draft = {
                    "to": ref["from"], "subject": subject, "body": text,
                    "in_reply_to": ref.get("message_id_header") or None,
                }
                save_email_draft(new_draft)
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": draft_prompt(new_draft)})
                    print("borrador de respuesta creado, esperando CONFIRMAR", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            new_draft = parse_draft_text(text, require_command=True)
            if new_draft:
                save_email_draft(new_draft)
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": draft_prompt(new_draft)})
                    print("borrador nuevo creado, esperando CONFIRMAR", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            natural_to = parse_natural_send(text)
            if natural_to:
                try:
                    api_call("sendChatAction", {"chat_id": CHAT_ID, "action": "typing"})
                except Exception:
                    pass
                try:
                    subject, body = generate_email_draft(natural_to, text)
                except Exception as e:
                    subject, body = None, None
                    print(f"generate_email_draft error: {e}", flush=True)
                if subject and body:
                    nl_draft = {"to": natural_to, "subject": subject, "body": body}
                    save_email_draft(nl_draft)
                    answer = draft_prompt(nl_draft)
                else:
                    answer = "No he podido redactar el correo, intentalo con /enviar y el formato Para:/Asunto:/cuerpo."
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                    print("borrador en lenguaje natural creado", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            tweet_draft = load_tweet_draft()
            if tweet_draft and CONFIRM_RE.match(text):
                clear_tweet_draft()
                answer = send_tweet(tweet_draft["text"])
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                    print(f"tweet: {answer[:80]}", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            tweet_cmd = TWEET_COMMAND_RE.match(text)
            if tweet_cmd:
                tweet_text = tweet_cmd.group("text").strip()[:280]
                save_tweet_draft(tweet_text)
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": tweet_prompt(tweet_text)})
                    print("borrador de tweet creado (texto exacto)", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            if TWEET_NATURAL_RE.search(text):
                try:
                    api_call("sendChatAction", {"chat_id": CHAT_ID, "action": "typing"})
                except Exception:
                    pass
                try:
                    tweet_text = generate_tweet_text(text)
                except Exception as e:
                    tweet_text = ""
                    print(f"generate_tweet_text error: {e}", flush=True)
                if tweet_text:
                    save_tweet_draft(tweet_text)
                    answer = tweet_prompt(tweet_text)
                else:
                    answer = "No he podido redactar el tweet, intentalo con /twittear y el texto exacto."
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                    print("borrador de tweet creado (lenguaje natural)", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            luces_req = parse_luces(text)
            if luces_req:
                target_key, action = luces_req
                try:
                    answer = run_luces(target_key, action)
                except Exception as e:
                    answer = f"Error controlando la luz: {e}"
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                    print(f"luces: {answer[:80]}", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            if WAKE_RE.search(text):
                try:
                    answer = send_wake_packet()
                except Exception as e:
                    answer = f"Error al mandar el magic packet: {e}"
                try:
                    api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                    print(f"wake ejecutado: {answer[:80]}", flush=True)
                except Exception as e:
                    print(f"sendMessage error: {e}", flush=True)
                continue
            try:
                api_call("sendChatAction", {"chat_id": CHAT_ID, "action": "typing"})
            except Exception:
                pass
            try:
                answer = ask_llm(text)
            except Exception as e:
                answer = f"Error consultando el modelo: {e}"
            try:
                api_call("sendMessage", {"chat_id": CHAT_ID, "text": answer})
                print(f"respondido: {answer[:80]}", flush=True)
            except Exception as e:
                print(f"sendMessage error: {e}", flush=True)


if __name__ == "__main__":
    main()
