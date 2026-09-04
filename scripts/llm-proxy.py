#!/data/data/com.termux/files/usr/bin/python3
"""Reverse proxy que arranca LFM2.5 bajo demanda y lo apaga tras estar
IDLE_TIMEOUT segundos sin peticiones (ponytail: hilo de vigilancia con
sleep fijo en vez de scheduler, sobra para un unico backend)."""
import http.server
import urllib.request
import urllib.error
import subprocess
import threading
import time

BACKEND_PORT = 8081
LISTEN_PORT = 8080
IDLE_TIMEOUT = 300
HOME = "/data/data/com.termux/files/home"
MODEL = f"{HOME}/models/LFM2.5-350M-Q4_K_M.gguf"
LLAMA_BIN = f"{HOME}/llama.cpp/build/bin/llama-server"
API_KEY = "elige-una-clave-cualquiera-para-el-servidor-local"  # misma clave que en scripts/lib.sh

proc = None
lock = threading.Lock()
last_request = time.time()


def backend_alive():
    return proc is not None and proc.poll() is None


def start_backend():
    global proc
    with lock:
        if backend_alive():
            return
        proc = subprocess.Popen(
            [LLAMA_BIN, "-m", MODEL, "--host", "127.0.0.1",
             "--port", str(BACKEND_PORT), "--api-key", API_KEY,
             "-c", "4096", "-t", "6"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/health", timeout=1)
            return
        except Exception:
            time.sleep(1)


def idle_watcher():
    global proc
    while True:
        time.sleep(30)
        if backend_alive() and time.time() - last_request > IDLE_TIMEOUT:
            with lock:
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    proc = None


class Handler(http.server.BaseHTTPRequestHandler):
    def _proxy(self):
        global last_request
        last_request = time.time()
        if not backend_alive():
            start_backend()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{BACKEND_PORT}{self.path}",
            data=body, method=self.command,
        )
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length"):
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    do_GET = _proxy
    do_POST = _proxy

    def log_message(self, fmt, *args):
        pass


threading.Thread(target=idle_watcher, daemon=True).start()
http.server.ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
