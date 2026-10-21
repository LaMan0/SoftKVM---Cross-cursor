"""Vérifie les callbacks de capture avec la signature réelle de pynput.

Ces tests ont besoin de pynput ; ils sont ignorés si la bibliothèque est absente.
"""

import unittest

try:
    from pynput.keyboard import Key
    from pynput.mouse import Button

    from softkvm.inputs import PynputCapture, key_spec
except ImportError:  # pragma: no cover - pynput non installé
    PynputCapture = None
    key_spec = None


class _Recorder:
    def __init__(self):
        self.events = []

    def on_move(self, x, y):
        self.events.append(("move", x, y))

    def on_click(self, x, y, name, pressed):
        self.events.append(("click", x, y, name, pressed))

    def on_scroll(self, x, y, dx, dy):
        self.events.append(("scroll", x, y, dx, dy))

    def on_key(self, spec, pressed):
        self.events.append(("key", spec, pressed))


@unittest.skipIf(PynputCapture is None, "pynput indisponible")
class PynputCallbackTests(unittest.TestCase):
    def setUp(self):
        self.recorder = _Recorder()
        self.capture = PynputCapture(self.recorder)

    def test_click_with_injected_flag_is_delivered(self):
        # Régression : pynput passe 5 arguments, ce qui levait une TypeError.
        self.capture._on_click(10, 20, Button.left, True, False)
        self.assertEqual(self.recorder.events, [("click", 10, 20, "left", True)])

    def test_click_without_injected_flag_is_delivered(self):
        self.capture._on_click(10, 20, Button.right, False)
        self.assertEqual(self.recorder.events, [("click", 10, 20, "right", False)])

    def test_injected_events_are_ignored(self):
        self.capture._on_click(10, 20, Button.left, True, True)
        self.capture._on_move(1, 2, True)
        self.capture._on_scroll(1, 2, 0, 1, True)
        self.capture._on_press(Key.ctrl, True)
        self.capture._on_release(Key.ctrl, True)
        self.assertEqual(self.recorder.events, [])

    def test_move_scroll_and_key_are_delivered(self):
        self.capture._on_move(3, 4)
        self.capture._on_scroll(3, 4, 0, -1, False)
        self.capture._on_press(Key.ctrl, False)
        self.capture._on_release(Key.ctrl, False)
        spec = key_spec(Key.ctrl)
        self.assertEqual(
            self.recorder.events,
            [
                ("move", 3, 4),
                ("scroll", 3, 4, 0, -1),
                ("key", spec, True),
                ("key", spec, False),
            ],
        )


if __name__ == "__main__":
    unittest.main()
