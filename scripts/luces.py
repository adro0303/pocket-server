#!/data/data/com.termux/files/usr/bin/python3
import sys
import json
import os
import tinytuya

HOME = "/data/data/com.termux/files/home"
DEVICES_FILE = os.path.join(HOME, "devices.json")

# ponytail: IPs fijas por ARP - el descubrimiento por broadcast de tinytuya
# no funciona en este Android (UDP broadcast bloqueado a nivel de app/ROM).
# Si el router reasigna estas IPs por DHCP, esto se rompe - lo robusto es
# reservar IP fija por MAC para estos 5 dispositivos en el router.
IP_BY_ID = {
    "bf08e8d30c5fc9a181aiue": "192.168.1.246",  # Pasillo
    "bf71c9b20d163b17d3sjqv": "192.168.1.191",  # Espejo
    "bf705a882fd1236db15eai": "192.168.1.239",  # Zapatero
    "bfa2ae13933610afd6pp9v": "192.168.1.248",  # Luz despacho
    "bf64c1ac08c0d430854xtz": "192.168.1.251",  # Luz salon
}

# ponytail: agrupacion solo a nivel de script, no en la app SmartLife (el
# usuario prefirio no tocar la organizacion real de salas en Tuya por ahora).
GROUPS = {
    "entrada": ["Espejo", "Zapatero"],
    "todas": ["Pasillo", "Espejo", "Zapatero", "Luz despacho", "Luz salon"],
}

# "marron": tono calido/anaranjado con saturacion moderada - a menor V se
# ve mas marron/tierra, a V alto se ve mas naranja vivo.
BROWN_H = 25 / 360.0
BROWN_S = 0.75


def load_devices():
    with open(DEVICES_FILE) as f:
        return {d["name"].lower(): d for d in json.load(f)}


def get_device(name):
    devs = load_devices()
    d = devs.get(name.lower())
    if not d:
        raise SystemExit(f"no encuentro '{name}'. Disponibles: {', '.join(devs)}")
    ip = IP_BY_ID.get(d["id"])
    if not ip:
        raise SystemExit(f"sin IP conocida para {name}")
    dev = tinytuya.BulbDevice(d["id"], ip, d["key"], version=3.5)
    dev.set_socketTimeout(5)
    dev.set_socketPersistent(False)
    return dev


def apply(name, action, pct=None):
    dev = get_device(name)
    if action == "on":
        dev.turn_on()
    elif action == "off":
        dev.turn_off()
    elif action == "brown":
        if pct is not None:
            v = max(0.0, min(1.0, int(pct) / 100.0))
        else:
            _, _, v = dev.colour_hsv()
        dev.set_hsv(BROWN_H, BROWN_S, v)
    elif action == "estado":
        print(name, dev.status())
        return
    else:
        raise SystemExit("accion debe ser on|off|brown|estado")
    print(f"{name}: {action}" + (f" {pct}%" if action == "brown" and pct else ""))


def resolve(target):
    return GROUPS.get(target.lower(), [target])


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("uso: luces.py <nombre|grupo> on|off|brown [pct]|estado")
        print(f"disponibles: {', '.join(load_devices())}")
        print(f"grupos: {', '.join(GROUPS)}")
        sys.exit(1)
    target, action = args[0], args[1].lower()
    pct = args[2] if len(args) > 2 else None
    for name in resolve(target):
        apply(name, action, pct)


if __name__ == "__main__":
    main()
