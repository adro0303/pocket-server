#!/data/data/com.termux/files/usr/bin/python3
"""Publica tweets/hilos en X (Twitter) via API v2, firmando OAuth1 a mano
(stdlib puro: hmac/hashlib/base64, sin dependencias nuevas). Credenciales
en ~/.twitter_creds (4 lineas: api_key, api_key_secret, access_token,
access_token_secret), fichero suelto que el usuario escribe el mismo -
mismo patron que ~/.imap_pass, nunca en un fichero de este repo."""
import base64
import hashlib
import hmac
import json
import secrets
import sys
import time
import urllib.parse
import urllib.request

CREDS_FILE = "/data/data/com.termux/files/home/.twitter_creds"
API_URL = "https://api.x.com/2/tweets"
MAX_LEN = 280


def _load_creds():
    with open(CREDS_FILE) as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    if len(lines) < 4:
        raise ValueError(f"{CREDS_FILE} necesita 4 lineas: api_key, api_key_secret, access_token, access_token_secret")
    return lines[0], lines[1], lines[2], lines[3]


def _oauth1_header(method, url, consumer_key, consumer_secret, token, token_secret):
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    # el body es JSON (no form-encoded), asi que la firma OAuth1 solo
    # cubre los oauth_* params - no hay query/form params en este endpoint
    param_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(oauth_params.items())
    )
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_string, safe=""),
    ])
    signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature
    header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return header


def post_tweet(text, reply_to=None):
    if len(text) > MAX_LEN:
        raise ValueError(f"tweet de {len(text)} caracteres, maximo {MAX_LEN}")
    consumer_key, consumer_secret, token, token_secret = _load_creds()
    auth_header = _oauth1_header("POST", API_URL, consumer_key, consumer_secret, token, token_secret)
    body = {"text": text}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": auth_header, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        return data["data"]["id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")


def build_digest_tweet(title, exp, link):
    # deja hueco de sobra para el link (X cuenta las URLs como 23
    # caracteres via t.co sea cual sea su longitud real - aqui se cuenta
    # el largo real tal cual, mas conservador, para quedarse corto)
    budget = MAX_LEN - len(link) - 2
    body = f"{title} — {exp}" if exp else title
    if len(body) > budget:
        body = body[: max(budget - 1, 0)].rstrip() + "…"
    return f"{body}\n{link}"


def post_thread(texts):
    """Manda una lista de textos como hilo (cada uno responde al anterior).
    Devuelve la lista de ids publicados con exito - puede ser mas corta
    que `texts` si algo falla a mitad, no reintenta el resto."""
    ids = []
    reply_to = None
    for text in texts:
        tweet_id = post_tweet(text, reply_to=reply_to)
        ids.append(tweet_id)
        reply_to = tweet_id
    return ids


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("uso: twitter.py tweet <texto>  |  twitter.py thread <texto1> <texto2> ...", file=sys.stderr)
        sys.exit(1)
    cmd, rest = sys.argv[1], sys.argv[2:]
    try:
        if cmd == "tweet":
            print(post_tweet(rest[0]))
        elif cmd == "thread":
            print(" ".join(post_thread(rest)))
        elif cmd == "digest":
            intro = rest[0]
            items = []
            for line in sys.stdin:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                items.append(build_digest_tweet(*parts))
            print(" ".join(post_thread([intro] + items)))
        else:
            print(f"comando desconocido: {cmd}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
