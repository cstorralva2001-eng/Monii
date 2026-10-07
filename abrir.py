"""Launch the local app in the background and open its browser page."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8501"


def healthy():
    try:
        with urllib.request.urlopen(URL + "/_stcore/health", timeout=2) as response:
            return response.status == 200 and response.read(64).strip() == b"ok"
    except (OSError, urllib.error.URLError):
        return False


def start():
    if healthy():
        return
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", 8501)) == 0:
            raise RuntimeError("El puerto 8501 esta ocupado. Revisa el servidor antes de volver a abrir Monii.")
    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise RuntimeError("Faltan dependencias. Sigue la instalacion de README.md o ejecuta iniciar.ps1.") from None
    log = ROOT / "data" / "servidor.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with log.open("ab", buffering=0) as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
             "--server.address=127.0.0.1", "--server.port=8501", "--server.headless=true"],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, **options,
        )
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if healthy():
            return
        if process.poll() is not None:
            break
        time.sleep(0.5)
    raise RuntimeError(f"Monii no pudo iniciarse. Revisa el registro: {log}")


if __name__ == "__main__":
    try:
        start()
        print(f"Monii disponible en {URL}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(URL)
    except Exception as exc:
        print(f"No se pudo abrir Monii: {exc}", file=sys.stderr)
        sys.exit(1)
