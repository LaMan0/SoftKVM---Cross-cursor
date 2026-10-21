"""Côté maître : celui dont le clavier et la souris sont branchés.

Machine à états simple :
- `active is None` : l'utilisateur travaille en local. Pousser le curseur contre
  un bord qui touche un client connecté l'envoie sur ce client (`enter`).
- `active == nom` : les entrées sont capturées et supprimées localement, puis
  transmises au client. Le curseur est recentré à chaque mouvement pour en
  mesurer le déplacement. Le client renvoie `edge` quand son curseur sort par un
  bord ; le maître reprend alors le contrôle ou passe à un autre client.
"""

import logging
import queue
import socket
import sys
import threading

from .protocol import (
    OPPOSITE,
    SIDES,
    decode,
    edge_at,
    edge_fraction,
    encode,
    entry_point,
    new_nonce,
    translate_spec,
    verify_mac,
)

log = logging.getLogger(__name__)


class _Session:
    """Une connexion client authentifiée, avec une file d'écriture dédiée.

    L'envoi ne bloque jamais l'appelant (souvent un callback de capture).
    """

    def __init__(self, name, platform, width, height, conn):
        self.name = name
        self.platform = platform
        self.width = width
        self.height = height
        self.conn = conn
        self._queue = queue.Queue()
        self._writer = threading.Thread(target=self._write_loop, daemon=True)

    def start(self):
        self._writer.start()

    def send(self, msg):
        self._queue.put(encode(msg))

    def close(self):
        self._queue.put(None)
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.conn.close()
        except OSError:
            pass

    def _write_loop(self):
        while True:
            data = self._queue.get()
            if data is None:
                return
            try:
                self.conn.sendall(data)
            except OSError:
                return


class Hub:
    """Serveur maître. `capture_factory(hub)` doit renvoyer un objet avec
    start/stop/set_suppress/set_cursor (ex. inputs.PynputCapture)."""

    def __init__(
        self,
        layout,
        layout_lock,
        password,
        master_name,
        size,
        capture_factory,
        notify=None,
    ):
        self.layout = layout
        self._lock = layout_lock
        self.password = password
        self.master_name = master_name
        self.width, self.height = int(size[0]), int(size[1])
        self.platform = sys.platform
        self.active = None
        self.port = None
        self._sessions = {}
        self._server = None
        self._running = False
        self._notify = notify or (lambda message: None)
        self.capture = capture_factory(self)

    # --- cycle de vie ----------------------------------------------------

    def start(self, host="0.0.0.0", port=0):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(8)
        self._server = server
        self.port = server.getsockname()[1]
        self._running = True
        with self._lock:
            self.layout.ensure(self.master_name, self.width, self.height, self.master_name)
        self.capture.start()
        threading.Thread(target=self._accept_loop, name="accept", daemon=True).start()
        self._notify(f"Serveur démarré sur le port {self.port}")

    def stop(self):
        self._running = False
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self.active = None
        for session in sessions:
            session.close()
        self.capture.stop()
        self._notify("Serveur arrêté")

    def connected(self):
        with self._lock:
            return sorted(self._sessions)

    # --- connexions ------------------------------------------------------

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server.accept()
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(
                target=self._serve, args=(conn, addr), name=f"client {addr}", daemon=True
            ).start()

    def _serve(self, conn, addr):
        session = None
        rfile = conn.makefile("rb")
        try:
            conn.settimeout(10)
            nonce = new_nonce()
            conn.sendall(encode({"t": "challenge", "nonce": nonce}))
            hello = decode(rfile.readline())
            if hello["t"] != "hello" or not verify_mac(self.password, nonce, hello.get("mac", "")):
                conn.sendall(encode({"t": "error", "msg": "mot de passe incorrect"}))
                log.warning("connexion refusée depuis %s", addr)
                return
            width, height = int(hello.get("w", 0)), int(hello.get("h", 0))
            if width <= 0 or height <= 0:
                conn.sendall(encode({"t": "error", "msg": "taille d'écran invalide"}))
                return
            base = str(hello.get("name") or addr[0])[:64]
            platform = str(hello.get("platform", ""))
            conn.settimeout(None)
            with self._lock:
                name = self._unique_name(base)
                session = _Session(name, platform, width, height, conn)
                session.start()
                session.send({"t": "welcome", "name": name})
                self._sessions[name] = session
                self.layout.ensure(name, width, height, self.master_name)
            self._notify(f"{name} connecté")
            for line in rfile:
                msg = decode(line)
                if msg["t"] == "edge":
                    try:
                        fraction = float(msg.get("f", 0.5))
                    except (TypeError, ValueError):
                        continue
                    self._on_client_edge(name, msg.get("side"), fraction)
        except (OSError, ValueError, KeyError, TypeError):
            log.info("connexion terminée (%s)", addr, exc_info=True)
        finally:
            rfile.close()
            if session is not None:
                self._drop(session)
            else:
                conn.close()

    def _unique_name(self, base):
        """Nom libre pour un client (appelé sous verrou)."""
        name, index = base, 2
        while name == self.master_name or name in self._sessions:
            name = f"{base} ({index})"
            index += 1
        return name

    def _drop(self, session):
        with self._lock:
            if self._sessions.get(session.name) is session:
                del self._sessions[session.name]
            if self.active == session.name:
                self.active = None
                self.capture.set_cursor(*self._center())
                self.capture.set_suppress(False)
        session.close()
        self._notify(f"{session.name} déconnecté")

    # --- passages de bord ------------------------------------------------

    def _center(self):
        return self.width // 2, self.height // 2

    def _active_session(self):
        return self._sessions.get(self.active) if self.active is not None else None

    def _on_client_edge(self, name, side, fraction):
        if side not in SIDES:
            return
        with self._lock:
            if self.active != name:
                return
            target = self.layout.neighbor(name, side)
            source = self._sessions.get(name)
            if target is None or source is None:
                return
            if target == self.master_name:
                source.send({"t": "leave"})
                self.active = None
                self.capture.set_cursor(*entry_point(OPPOSITE[side], fraction, self.width, self.height))
                self.capture.set_suppress(False)
                self._notify("Contrôle : ce PC")
                return
            dest = self._sessions.get(target)
            if dest is None:
                return
            source.send({"t": "leave"})
            dest.send({"t": "enter", "side": OPPOSITE[side], "f": fraction})
            self.active = target
            self._notify(f"Contrôle : {target}")

    # --- entrées locales (appelées par la capture) -----------------------

    def on_move(self, x, y):
        with self._lock:
            if self.active is None:
                side = edge_at(x, y, self.width, self.height)
                if side is None:
                    return
                target = self.layout.neighbor(self.master_name, side)
                session = self._sessions.get(target) if target is not None else None
                if session is None:
                    return
                fraction = edge_fraction(side, x, y, self.width, self.height)
                self.active = session.name
                session.send({"t": "enter", "side": OPPOSITE[side], "f": fraction})
                self.capture.set_cursor(*self._center())
                self.capture.set_suppress(True)
                self._notify(f"Contrôle : {session.name}")
                return
            session = self._active_session()
            if session is None:
                return
            cx, cy = self._center()
            dx, dy = x - cx, y - cy
            if dx or dy:
                session.send({"t": "move", "dx": dx, "dy": dy})
                self.capture.set_cursor(cx, cy)

    def on_click(self, x, y, button, pressed):
        with self._lock:
            session = self._active_session()
            if session is not None:
                session.send({"t": "btn", "b": button, "p": pressed})

    def on_scroll(self, x, y, dx, dy):
        with self._lock:
            session = self._active_session()
            if session is not None:
                session.send({"t": "scroll", "dx": dx, "dy": dy})

    def on_key(self, spec, pressed):
        with self._lock:
            session = self._active_session()
            if session is None:
                return
            mapped = translate_spec(spec, self.platform, session.platform)
            if mapped is not None:
                session.send({"t": "key", "d": pressed, "s": mapped})
