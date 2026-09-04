import socket
mac = "AA:BB:CC:DD:EE:FF"  # MAC de la tarjeta de red del PC a encender (ip link / ipconfig)
BROADCAST_IP = "192.168.1.255"  # broadcast de tu LAN - ajusta al /24 real de tu router
packet = bytes.fromhex("FF" * 6 + mac.replace(":", "") * 16)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
s.sendto(packet, (BROADCAST_IP, 9))
s.close()
print("Magic packet enviado a", mac)
