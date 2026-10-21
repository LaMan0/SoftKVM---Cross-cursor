"""Tests de SoftKVM. Lancer depuis la racine : python -m unittest tests.test_softkvm -v

Aucun test n'utilise pynput : la capture et l'injection sont remplacées par des
faux objets, ce qui permet de tester la logique réseau et les passages de bord
sur n'importe quelle machine.
"""

import threading
import time
import unittest

from softkvm.client import Client
from softkvm.hub import Hub
from softkvm.layout import Layout, Rect
from softkvm.protocol import (
    compute_mac,
    decode,
    edge_at,
    edge_fraction,
    encode,
    entry_point,
    normalize_char,
    translate_spec,
    verify_mac,
)


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class FakeCapture:
    def __init__(self):
        self.suppress = False
        self.cursor_calls = []
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def set_suppress(self, enabled):
        self.suppress = bool(enabled)

    def set_cursor(self, x, y):
        self.cursor_calls.append((x, y))


class FakeInjector:
    def __init__(self, pos=(0, 0)):
        self.pos = pos
        self.keys = []
        self.buttons = []
        self.scrolls = []

    def cursor(self):
        return self.pos

    def set_cursor(self, x, y):
        self.pos = (int(x), int(y))

    def scroll(self, dx, dy):
        self.scrolls.append((dx, dy))

    def press_button(self, name, down):
        self.buttons.append((name, down))

    def press_key(self, spec, down):
        self.keys.append((spec, down))


class ProtocolTests(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        msg = {"t": "move", "dx": -3, "dy": 4}
        self.assertEqual(decode(encode(msg).rstrip(b"\n")), msg)

    def test_decode_rejects_invalid_messages(self):
        with self.assertRaises(ValueError):
            decode(b"[1, 2]")
        with self.assertRaises(ValueError):
            decode(b"not json")

    def test_mac_verification(self):
        mac = compute_mac("secret", "nonce1")
        self.assertTrue(verify_mac("secret", "nonce1", mac))
        self.assertFalse(verify_mac("other", "nonce1", mac))
        self.assertFalse(verify_mac("secret", "nonce2", mac))
        self.assertFalse(verify_mac("secret", "nonce1", None))

    def test_edge_detection(self):
        self.assertEqual(edge_at(0, 500, 1920, 1080), "left")
        self.assertEqual(edge_at(1919, 500, 1920, 1080), "right")
        self.assertEqual(edge_at(500, 0, 1920, 1080), "top")
        self.assertEqual(edge_at(500, 1079, 1920, 1080), "bottom")
        self.assertIsNone(edge_at(500, 500, 1920, 1080))

    def test_fraction_and_entry_point_are_consistent(self):
        fraction = edge_fraction("right", 1919, 540, 1920, 1080)
        x, y = entry_point("left", fraction, 1440, 900)
        self.assertEqual(x, 2)
        self.assertAlmostEqual(y / 899, fraction, delta=0.01)

    def test_entry_point_clamps_fraction(self):
        self.assertEqual(entry_point("top", 5, 100, 100), (99, 2))
        self.assertEqual(entry_point("bottom", -1, 100, 100), (0, 97))

    def test_control_characters_become_letters(self):
        self.assertEqual(normalize_char("\x03"), "c")  # Ctrl+C
        self.assertEqual(normalize_char("\r"), "\r")   # Entrée reste Entrée
        self.assertEqual(normalize_char("\t"), "\t")
        self.assertEqual(normalize_char("a"), "a")
        self.assertIsNone(normalize_char(""))

    def test_cmd_and_ctrl_are_swapped_between_mac_and_windows(self):
        self.assertEqual(translate_spec({"k": "cmd"}, "darwin", "win32"), {"k": "ctrl"})
        self.assertEqual(translate_spec({"k": "ctrl_r"}, "win32", "darwin"), {"k": "cmd_r"})
        self.assertEqual(translate_spec({"k": "shift"}, "darwin", "win32"), {"k": "shift"})
        self.assertEqual(translate_spec({"k": "cmd"}, "darwin", "darwin"), {"k": "cmd"})

    def test_virtual_key_codes_are_dropped_across_platforms(self):
        self.assertIsNone(translate_spec({"vk": 65}, "win32", "darwin"))
        self.assertEqual(translate_spec({"vk": 65}, "win32", "win32"), {"vk": 65})
        self.assertIsNone(translate_spec(None, "win32", "win32"))


class LayoutTests(unittest.TestCase):
    def test_new_screen_is_placed_to_the_right(self):
        layout = Layout()
        layout.ensure("PC", 1920, 1080, "PC")
        layout.ensure("Mac", 1440, 900, "PC")
        self.assertEqual(layout.screens["Mac"], Rect(1920, 0, 1440, 900))
        self.assertEqual(layout.neighbor("PC", "right"), "Mac")
        self.assertEqual(layout.neighbor("Mac", "left"), "PC")
        self.assertIsNone(layout.neighbor("PC", "left"))

    def test_new_screen_does_not_overlap(self):
        layout = Layout()
        layout.ensure("PC", 1920, 1080, "PC")
        layout.ensure("A", 1920, 1080, "PC")
        layout.ensure("B", 1920, 1080, "PC")
        self.assertNotEqual(layout.screens["A"], layout.screens["B"])
        self.assertEqual(layout.neighbor("PC", "right"), "A")

    def test_ensure_updates_size_of_known_screen(self):
        layout = Layout()
        layout.ensure("PC", 1920, 1080, "PC")
        layout.ensure("PC", 2560, 1440, "PC")
        self.assertEqual((layout.screens["PC"].w, layout.screens["PC"].h), (2560, 1440))

    def test_snap_glues_screen_to_neighbor(self):
        layout = Layout()
        layout.ensure("PC", 1920, 1080, "PC")
        layout.ensure("Mac", 1440, 900, "PC")
        layout.move("Mac", 1930, 20)  # un peu trop loin à droite
        x, y = layout.snap("Mac", 1930, 20)
        self.assertEqual(x, 1920)

    def test_snap_ignores_far_positions(self):
        layout = Layout()
        layout.ensure("PC", 1920, 1080, "PC")
        layout.ensure("Mac", 1440, 900, "PC")
        self.assertEqual(layout.snap("Mac", 5000, 5000), (5000, 5000))

    def test_persistence_skips_corrupted_entries(self):
        layout = Layout.from_dict(
            {"PC": {"x": 0, "y": 0, "w": 1920, "h": 1080}, "bad": {"x": "oops"}, "x": None}
        )
        self.assertEqual(set(layout.screens), {"PC"})
        self.assertEqual(Layout.from_dict(layout.to_dict()).to_dict(), layout.to_dict())


class HubClientTests(unittest.TestCase):
    """Test de bout en bout sur localhost : PC (maître) à gauche, Mac (client) à droite."""

    PASSWORD = "secret-test"

    def setUp(self):
        self.layout = Layout()
        self.lock = threading.Lock()
        self.layout.ensure("PC", 1920, 1080, "PC")
        self.captures = []

        def factory(hub):
            capture = FakeCapture()
            self.captures.append(capture)
            return capture

        self.hub = Hub(
            self.layout, self.lock, self.PASSWORD, "PC", (1920, 1080), factory
        )
        self.hub.start(host="127.0.0.1", port=0)
        self.capture = self.captures[0]
        self.injector = FakeInjector()
        self.client = Client(
            "127.0.0.1", self.hub.port, self.PASSWORD, "Mac", (1440, 900), self.injector
        )
        self.client.connect()
        self.assertTrue(wait_for(lambda: self.hub.connected() == ["Mac"]))

    def tearDown(self):
        self.client.close()
        self.hub.stop()

    def test_wrong_password_is_refused(self):
        bad = Client("127.0.0.1", self.hub.port, "wrong", "Intrus", (800, 600), FakeInjector())
        with self.assertRaises(ConnectionError):
            bad.connect()
        self.assertEqual(self.hub.connected(), ["Mac"])

    def test_client_is_placed_in_layout(self):
        self.assertEqual(self.layout.neighbor("PC", "right"), "Mac")

    def test_cursor_crosses_to_client_and_back(self):
        # Le curseur sur le bord droit du PC passe sur le Mac.
        self.hub.on_move(1919, 540)
        self.assertTrue(wait_for(lambda: self.injector.pos[0] == 2))
        self.assertEqual(self.hub.active, "Mac")
        self.assertTrue(self.capture.suppress)
        self.assertEqual(self.injector.pos, (2, round(540 / 1079 * 899)))

        # Les mouvements sont relayés en deltas par rapport au centre.
        center = (960, 540)
        self.hub.on_move(center[0] + 5, center[1])
        self.assertTrue(wait_for(lambda: self.injector.pos[0] == 7))

        # Touches et boutons vont au client.
        self.hub.on_key({"c": "a"}, True)
        self.hub.on_key({"c": "a"}, False)
        self.hub.on_click(960, 540, "left", True)
        self.hub.on_click(960, 540, "left", False)
        self.hub.on_scroll(960, 540, 0, -1)
        self.assertTrue(wait_for(lambda: len(self.injector.keys) == 2))
        self.assertEqual(self.injector.keys, [({"c": "a"}, True), ({"c": "a"}, False)])
        self.assertTrue(wait_for(lambda: len(self.injector.buttons) == 2))
        self.assertTrue(wait_for(lambda: self.injector.scrolls == [(0, -1)]))

        # Le curseur sort par le bord gauche du Mac : retour sur le PC.
        self.hub.on_move(center[0] - 20, center[1])  # dx négatif, le client va vers son bord gauche
        self.assertTrue(wait_for(lambda: self.hub.active is None))
        self.assertFalse(self.capture.suppress)
        self.assertEqual(self.capture.cursor_calls[-1][0], 1920 - 1 - 2)

    def test_local_input_is_not_forwarded_when_not_on_client(self):
        self.hub.on_key({"c": "x"}, True)
        self.hub.on_move(500, 500)
        time.sleep(0.1)
        self.assertEqual(self.injector.keys, [])
        self.assertIsNone(self.hub.active)

    def test_edge_without_neighbor_keeps_local_control(self):
        self.hub.on_move(0, 540)  # bord gauche du PC : rien à gauche
        self.assertIsNone(self.hub.active)
        self.assertFalse(self.capture.suppress)

    def test_client_disconnect_returns_control_to_master(self):
        self.hub.on_move(1919, 540)
        self.assertTrue(wait_for(lambda: self.hub.active == "Mac"))
        self.client.close()
        self.assertTrue(wait_for(lambda: self.hub.active is None))
        self.assertTrue(wait_for(lambda: self.hub.connected() == []))
        self.assertFalse(self.capture.suppress)


if __name__ == "__main__":
    unittest.main()
