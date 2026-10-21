"""Adaptateurs pynput : capture globale et injection d'événements.

Capture : pynput ne permet pas de changer `suppress` à chaud. Quand on passe en
mode « distant », on arrête les listeners et on en recrée avec suppress=True
(les événements n'atteignent alors plus le système local). Le redémarrage se
fait dans un thread dédié pour ne jamais bloquer un callback de capture.

Les callbacks reçoivent des valeurs simples (dict pour les touches, nom pour
les boutons) pour que la logique métier reste indépendante de pynput.
"""

import logging
import threading

from pynput import keyboard, mouse

from .protocol import normalize_char

log = logging.getLogger(__name__)


def key_spec(key):
    """Représentation sérialisable d'une touche pynput, ou None."""
    if isinstance(key, keyboard.Key):
        return {"k": key.name}
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            char = normalize_char(key.char)
            if char:
                return {"c": char}
        if key.vk is not None:
            return {"vk": int(key.vk)}
    return None


def spec_to_key(spec):
    """Inverse de key_spec : pynput Key/KeyCode, ou None si non reconnu."""
    try:
        if "k" in spec:
            return keyboard.Key[spec["k"]]
        if "c" in spec:
            return keyboard.KeyCode.from_char(spec["c"])
        if "vk" in spec:
            return keyboard.KeyCode.from_vk(int(spec["vk"]))
    except (KeyError, TypeError, ValueError):
        log.debug("touche inconnue ignorée : %r", spec)
    return None


class PynputCapture:
    """Capture globale souris + clavier, avec suppression basculable.

    `handler` doit fournir : on_move(x, y), on_click(x, y, button_name, pressed),
    on_scroll(x, y, dx, dy), on_key(spec, pressed). Les exceptions levées par le
    handler sont journalisées : sinon pynput arrêterait le listener.
    """

    def __init__(self, handler):
        self._handler = handler
        self._mouse_listener = None
        self._key_listener = None
        self._suppress = False
        self._want = False
        self._wake = threading.Event()
        self._stopped = False
        self._worker = threading.Thread(target=self._run, name="capture", daemon=True)
        self._mouse_ctl = mouse.Controller()
        self._key_ctl = keyboard.Controller()

    # --- cycle de vie -----------------------------------------------------

    def start(self):
        self._apply(False)
        self._worker.start()

    def stop(self):
        self._stopped = True
        self._wake.set()
        self._stop_listeners()

    def set_suppress(self, enabled):
        """Demande de (dés)activer la suppression. Non bloquant."""
        self._want = bool(enabled)
        self._wake.set()

    # --- pilotage du curseur ---------------------------------------------

    def cursor(self):
        x, y = self._mouse_ctl.position
        return int(x), int(y)

    def set_cursor(self, x, y):
        self._mouse_ctl.position = (int(x), int(y))

    # --- interne ----------------------------------------------------------

    def _run(self):
        while not self._stopped:
            self._wake.wait()
            self._wake.clear()
            if self._stopped:
                break
            want = self._want
            if want != self._suppress:
                try:
                    self._apply(want)
                except Exception:  # noqa: BLE001 - on journalise et on continue
                    log.exception("impossible de changer la capture")

    def _apply(self, suppress):
        self._stop_listeners()
        self._mouse_listener = mouse.Listener(
            on_move=self._safe(self._on_move),
            on_click=self._safe(self._on_click),
            on_scroll=self._safe(self._on_scroll),
            suppress=suppress,
        )
        self._key_listener = keyboard.Listener(
            on_press=self._safe(self._on_press),
            on_release=self._safe(self._on_release),
            suppress=suppress,
        )
        self._mouse_listener.start()
        self._key_listener.start()
        self._mouse_listener.wait()
        self._key_listener.wait()
        self._suppress = suppress

    def _stop_listeners(self):
        for listener in (self._mouse_listener, self._key_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:  # noqa: BLE001
                    log.debug("arrêt d'un listener", exc_info=True)
        self._mouse_listener = None
        self._key_listener = None

    def _safe(self, fn):
        def wrapper(*args):
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 - ne jamais laisser pynput s'arrêter
                log.exception("erreur dans le gestionnaire d'événement")
            # Ne retourne jamais False : cela arrêterait le listener.

        return wrapper

    # pynput passe un drapeau `injected` (True si l'événement vient d'une
    # injection logicielle). On l'ignore pour ne pas recapturer nos propres
    # injections, et on accepte les versions qui ne le fournissent pas.

    def _on_move(self, x, y, injected=False):
        if injected:
            return
        self._handler.on_move(int(x), int(y))

    def _on_click(self, x, y, button, pressed, injected=False):
        if injected:
            return
        name = getattr(button, "name", None)
        if name:
            self._handler.on_click(int(x), int(y), name, bool(pressed))

    def _on_scroll(self, x, y, dx, dy, injected=False):
        if injected:
            return
        self._handler.on_scroll(int(x), int(y), int(dx), int(dy))

    def _on_press(self, key, injected=False):
        if injected:
            return
        spec = key_spec(key)
        if spec is not None:
            self._handler.on_key(spec, True)

    def _on_release(self, key, injected=False):
        if injected:
            return
        spec = key_spec(key)
        if spec is not None:
            self._handler.on_key(spec, False)


class PynputInjector:
    """Injection d'événements (souris et clavier) sur ce PC."""

    def __init__(self):
        self._mouse = mouse.Controller()
        self._keys = keyboard.Controller()

    def cursor(self):
        x, y = self._mouse.position
        return int(x), int(y)

    def set_cursor(self, x, y):
        self._mouse.position = (int(x), int(y))

    def move_by(self, dx, dy):
        self._mouse.move(int(dx), int(dy))

    def scroll(self, dx, dy):
        self._mouse.scroll(int(dx), int(dy))

    def press_button(self, name, down):
        button = getattr(mouse.Button, name, None)
        if button is None:
            return
        if down:
            self._mouse.press(button)
        else:
            self._mouse.release(button)

    def press_key(self, spec, down):
        key = spec_to_key(spec)
        if key is None:
            return
        if down:
            self._keys.press(key)
        else:
            self._keys.release(key)
