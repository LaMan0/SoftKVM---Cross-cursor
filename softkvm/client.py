"""Côté client : le PC contrôlé par le maître.

Reçoit les événements (enter / leave / move / btn / scroll / key), les rejoue
avec l'injecteur, et envoie `edge` quand le curseur sort par un bord.
"""

import json
import logging
import socket
import sys
import threading

from .protocol import (
    compute_mac,
    decode,
    edge_fraction,
    encode,
    entry_point,
)

log = logging.getLogger(__name__)


class Client:
    """`injector` doit fournir : cursor(), set_cursor(x, y), press_key(spec, down),
    press_button(name, down), scroll(dx, dy)."""

    def __init__(self, host, port, password, name, size, injector, notify=None):
        self.host = host
        self.port = int(port)
        self.password = password
        self.name = name
        self.width, self.height = int(size[0]), int(size[1])
        self.injector = injector
        self._notify = notify or (lambda message: None)
        self._sock = None
        self._send_lock = threading.Lock()
        self._active = False
        self._held_keys = {}      # identifiant JSON -> spec
        self._held_buttons = set()

    # --- connexion -------------------------------------------------------

    @property
    def connected(self):
        return self._sock is not None

    def connect(self, timeout=5):
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(timeout)
        rfile = sock.makefile("rb")
        try:
            challenge = decode(rfile.readline())
            if challenge["t"] != "challenge":
                raise ConnectionError("réponse inattendue du serveur")
            hello = {
                "t": "hello",
                "name": self.name,
                "platform": sys.platform,
                "w": self.width,
                "h": self.height,
                "mac": compute_mac(self.password, challenge["nonce"]),
            }
            sock.sendall(encode(hello))
            reply = decode(rfile.readline())
            if reply["t"] != "welcome":
                raise ConnectionError(reply.get("msg", "connexion refusée"))
        except (ValueError, KeyError, OSError) as exc:
            rfile.close()
            sock.close()
            raise ConnectionError(str(exc)) from exc
        sock.settimeout(None)
        self.name = reply.get("name", self.name)
        self._sock = sock
        threading.Thread(target=self._read_loop, args=(rfile,), name="client-read", daemon=True).start()
        self._notify(f"Connecté au serveur {self.host}")

    def close(self):
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _send(self, msg):
        sock = self._sock
        if sock is None:
            return
        with self._send_lock:
            try:
                sock.sendall(encode(msg))
            except OSError:
                log.info("envoi impossible, connexion perdue")

    # --- réception -------------------------------------------------------

    def _read_loop(self, rfile):
        try:
            for line in rfile:
                self._handle(decode(line))
        except (OSError, ValueError):
            log.info("connexion au serveur interrompue", exc_info=True)
        finally:
            rfile.close()
            self._release_all()
            self._active = False
            self._sock = None
            self._notify("Déconnecté du serveur")

    def _handle(self, msg):
        kind = msg["t"]
        if kind == "enter":
            x, y = entry_point(msg["side"], msg["f"], self.width, self.height)
            self.injector.set_cursor(x, y)
            self._active = True
            self._notify("Contrôlé par le serveur")
        elif kind == "leave":
            self._active = False
            self._release_all()
            self._notify(f"Connecté au serveur {self.host}")
        elif not self._active:
            return
        elif kind == "move":
            self._move(int(msg["dx"]), int(msg["dy"]))
        elif kind == "btn":
            self._button(msg["b"], bool(msg["p"]))
        elif kind == "scroll":
            self.injector.scroll(int(msg["dx"]), int(msg["dy"]))
        elif kind == "key":
            self._key(msg["s"], bool(msg["d"]))

    def _move(self, dx, dy):
        cx, cy = self.injector.cursor()
        rx, ry = cx + dx, cy + dy
        side = None
        if rx <= 0 and dx < 0:
            side = "left"
        elif rx >= self.width - 1 and dx > 0:
            side = "right"
        elif ry <= 0 and dy < 0:
            side = "top"
        elif ry >= self.height - 1 and dy > 0:
            side = "bottom"
        nx = max(0, min(self.width - 1, rx))
        ny = max(0, min(self.height - 1, ry))
        if (nx, ny) != (cx, cy):
            self.injector.set_cursor(nx, ny)
        if side is not None:
            fraction = edge_fraction(side, nx, ny, self.width, self.height)
            self._send({"t": "edge", "side": side, "f": fraction})

    def _button(self, name, pressed):
        self.injector.press_button(name, pressed)
        if pressed:
            self._held_buttons.add(name)
        else:
            self._held_buttons.discard(name)

    def _key(self, spec, pressed):
        ident = json.dumps(spec, sort_keys=True)
        self.injector.press_key(spec, pressed)
        if pressed:
            self._held_keys[ident] = spec
        else:
            self._held_keys.pop(ident, None)

    def _release_all(self):
        """Relâche toutes les touches et boutons restés enfoncés (évite les touches bloquées)."""
        for spec in list(self._held_keys.values()):
            self.injector.press_key(spec, False)
        for name in list(self._held_buttons):
            self.injector.press_button(name, False)
        self._held_keys.clear()
        self._held_buttons.clear()
