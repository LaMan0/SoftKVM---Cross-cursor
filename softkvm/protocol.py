"""Fonctions pures partagées par le serveur (maître) et le client.

Aucune dépendance à pynput ni à tkinter : tout ce module est testable partout.
"""

import hashlib
import hmac
import json
import secrets

DEFAULT_PORT = 24800

# Distance (px) à l'intérieur de l'écran où le curseur est replacé après un passage.
# Évite qu'un retour immédiat sur le bord déclenche un nouveau passage.
INSET = 2

SIDES = ("left", "right", "top", "bottom")
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}

# Caractères de contrôle qui ne sont PAS des raccourcis Ctrl+lettre.
_KEPT_CONTROL_CHARS = {8, 9, 10, 13}


def encode(msg):
    """Sérialise un message en une ligne JSON terminée par un saut de ligne."""
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line):
    """Désérialise une ligne reçue. Lève ValueError si le message est invalide."""
    msg = json.loads(line.decode("utf-8"))
    if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
        raise ValueError("message invalide")
    return msg


# --- Authentification -------------------------------------------------------

def new_nonce():
    return secrets.token_hex(16)


def compute_mac(password, nonce):
    return hmac.new(
        password.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_mac(password, nonce, mac):
    return hmac.compare_digest(compute_mac(password, nonce), str(mac))


# --- Géométrie des bords ----------------------------------------------------

def edge_at(x, y, width, height):
    """Retourne le bord de l'écran touché par le point (x, y), ou None."""
    if x <= 0:
        return "left"
    if x >= width - 1:
        return "right"
    if y <= 0:
        return "top"
    if y >= height - 1:
        return "bottom"
    return None


def edge_fraction(side, x, y, width, height):
    """Position relative (0..1) du point le long du bord, pour transmettre à l'autre écran."""
    if side in ("left", "right"):
        fraction = y / max(height - 1, 1)
    else:
        fraction = x / max(width - 1, 1)
    return min(max(fraction, 0.0), 1.0)


def entry_point(side, fraction, width, height):
    """Point où le curseur apparaît lorsqu'il entre par le bord `side`."""
    fraction = min(max(float(fraction), 0.0), 1.0)
    if side == "left":
        x, y = INSET, fraction * (height - 1)
    elif side == "right":
        x, y = width - 1 - INSET, fraction * (height - 1)
    elif side == "top":
        x, y = fraction * (width - 1), INSET
    else:  # bottom
        x, y = fraction * (width - 1), height - 1 - INSET
    x = min(max(int(round(x)), 0), width - 1)
    y = min(max(int(round(y)), 0), height - 1)
    return x, y


# --- Touches ----------------------------------------------------------------

_CMD_CTRL_SWAP = {
    "ctrl": "cmd", "ctrl_l": "cmd_l", "ctrl_r": "cmd_r",
    "cmd": "ctrl", "cmd_l": "ctrl_l", "cmd_r": "ctrl_r",
}


def normalize_char(char):
    """Convertit Ctrl+lettre (caractère de contrôle) en la lettre minuscule.

    Sous Windows et macOS, pynput renvoie '\\x03' pour Ctrl+C. Le client, qui
    reçoit aussi l'état de Ctrl, doit recevoir 'c' pour reconstituer le raccourci.
    Retourne None si le caractère n'est pas exploitable.
    """
    if not char:
        return None
    code = ord(char[0])
    if code < 32 and code not in _KEPT_CONTROL_CHARS:
        if 1 <= code <= 26:
            return chr(code + 96)
        return None
    return char


def translate_spec(spec, src_platform, dst_platform):
    """Adapte une touche envoyée d'une plateforme à une autre.

    - Entre macOS et Windows, Cmd et Ctrl sont échangés (Cmd+C -> Ctrl+C).
    - Les codes virtuels (`vk`) ne sont pas compatibles entre OS : on les ignore.
    Retourne le spec adapté, ou None si la touche ne doit pas être transmise.
    """
    if spec is None:
        return None
    if "vk" in spec and src_platform != dst_platform:
        return None
    if "k" in spec and {src_platform, dst_platform} == {"darwin", "win32"}:
        return {"k": _CMD_CTRL_SWAP.get(spec["k"], spec["k"])}
    return spec


def clamp(value, low, high):
    return max(low, min(high, value))
