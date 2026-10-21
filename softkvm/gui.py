"""Interface graphique (tkinter).

- Onglet « Serveur » : démarre le maître et permet d'organiser les écrans
  par glisser-déposer (l'écran de ce PC est bleu, les clients connectés verts).
- Onglet « Client » : se connecte à un maître pour être contrôlé.

Les threads réseau ne touchent jamais à tkinter : ils déposent des fonctions
dans `self.events`, exécutées par `_pump` dans le thread de l'interface.
"""

import json
import logging
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from .client import Client
from .hub import Hub
from .inputs import PynputCapture, PynputInjector
from .layout import Layout, Rect
from .protocol import DEFAULT_PORT

log = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".softkvm.json")
MARGIN = 24

# Palette
BG = "#eef1f7"
CARD = "#ffffff"
TEXT = "#1e2330"
MUTED = "#6b7280"
BORDER = "#dfe3ec"
ACCENT = "#4f46e5"
ACCENT_DARK = "#4338ca"
ACCENT_LIGHT = "#c7d2fe"
SUCCESS = "#16a34a"
WARNING = "#d97706"
DANGER = "#dc2626"
DANGER_DARK = "#b91c1c"
DANGER_LIGHT = "#fca5a5"
NEUTRAL = "#e5e7eb"
NEUTRAL_DARK = "#d1d5db"
IDLE = "#9ca3af"
CANVAS_BG = "#f8fafc"

# (fond, contour) selon l'état d'un écran sur la disposition
SCREEN_COLORS = {
    "master": ("#e0e7ff", ACCENT),
    "active": ("#fef3c7", WARNING),
    "connected": ("#dcfce7", SUCCESS),
    "offline": ("#f1f3f7", IDLE),
}


def lan_address():
    """Adresse IPv4 locale utilisée sur le réseau (à saisir sur les autres PC)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))  # aucun paquet n'est envoyé
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        log.warning("impossible d'enregistrer %s", CONFIG_PATH)


def _font_family():
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "Helvetica"


def _round_rect(canvas, x0, y0, x1, y1, radius, **options):
    r = max(0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    points = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **options)


class App:
    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.master_name = (socket.gethostname() or "Ce PC")[:64]
        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()

        self.layout_lock = threading.Lock()
        self.layout = Layout.from_dict(self.config.get("layout"))
        with self.layout_lock:
            self.layout.ensure(self.master_name, self.screen_w, self.screen_h, self.master_name)
        self._saved_layout = None

        self.events = queue.Queue()
        self.hub = None
        self.client = None
        self._connecting = False
        self._drag = None          # (nom, décalage x, décalage y) en coordonnées de disposition
        self._selected = None
        self._view = None          # (minx, miny, échelle, marge) du dernier dessin
        self._hit = {}             # nom -> rectangle canvas, pour le clic

        root.title("SoftKVM")
        root.geometry("960x910")
        root.minsize(880, 840)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.password = tk.StringVar(value=self.config.get("password", ""))
        self.status = tk.StringVar(value="Prêt")
        self._setup_style()
        self._build()
        self.root.after(200, self._pump)

    # --- thème -------------------------------------------------------------

    def _setup_style(self):
        family = _font_family()
        self.fonts = {
            "title": tkfont.Font(family=family, size=20, weight="bold"),
            "h2": tkfont.Font(family=family, size=13, weight="bold"),
            "bold": tkfont.Font(family=family, size=10, weight="bold"),
            "body": tkfont.Font(family=family, size=10),
            "small": tkfont.Font(family=family, size=9),
            "big": tkfont.Font(family=family, size=17, weight="bold"),
        }
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=family, size=10)

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=self.fonts["body"])

        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Heading.TLabel", background=CARD, foreground=TEXT, font=self.fonts["h2"])
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=self.fonts["small"])
        style.configure("Big.TLabel", background=CARD, foreground=ACCENT, font=self.fonts["big"])
        style.configure("Page.TLabel", background=BG, foreground=MUTED, padding=(24, 8))

        style.configure(
            "TEntry", fieldbackground=CARD, foreground=TEXT, bordercolor=BORDER,
            lightcolor=BORDER, darkcolor=BORDER, padding=(8, 6),
        )
        style.map(
            "TEntry", bordercolor=[("focus", ACCENT)],
            lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)],
        )

        self._button_style("TButton", NEUTRAL, NEUTRAL_DARK, TEXT, "#f3f4f6", "#9ca3af")
        self._button_style("Accent.TButton", ACCENT, ACCENT_DARK, "#ffffff", ACCENT_LIGHT, "#ffffff")
        self._button_style("Danger.TButton", DANGER, DANGER_DARK, "#ffffff", DANGER_LIGHT, "#ffffff")
        style.configure("TButton", font=self.fonts["body"], padding=(14, 8), focusthickness=0)
        style.configure("Accent.TButton", font=self.fonts["bold"], padding=(18, 9))
        style.configure("Danger.TButton", font=self.fonts["bold"], padding=(18, 9))

        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab", background=BG, foreground=MUTED, font=self.fonts["bold"],
            padding=(22, 10), borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", CARD), ("active", "#e3e8f2")],
            foreground=[("selected", ACCENT)],
        )

    def _button_style(self, name, normal, hover, fg, disabled_bg, disabled_fg):
        style = ttk.Style(self.root)
        style.configure(
            name, background=normal, foreground=fg, bordercolor=normal,
            lightcolor=normal, darkcolor=normal, relief="flat", borderwidth=0,
        )
        style.map(
            name,
            background=[("disabled", disabled_bg), ("pressed", hover), ("active", hover)],
            foreground=[("disabled", disabled_fg)],
            bordercolor=[("disabled", disabled_bg), ("active", hover)],
            lightcolor=[("disabled", disabled_bg), ("active", hover)],
            darkcolor=[("disabled", disabled_bg), ("active", hover)],
        )

    # --- construction de l'interface -----------------------------------

    def _build(self):
        status_bar = ttk.Label(self.root, textvariable=self.status, style="Page.TLabel", anchor="w")
        status_bar.pack(fill="x", side="bottom")

        page = tk.Frame(self.root, bg=BG)
        page.pack(fill="both", expand=True, padx=24, pady=(20, 0))

        header = tk.Frame(page, bg=BG)
        header.pack(fill="x")
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="SoftKVM", font=self.fonts["title"], bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(
            titles, text="Un seul clavier et une seule souris pour tous vos ordinateurs",
            font=self.fonts["body"], bg=BG, fg=MUTED,
        ).pack(anchor="w")
        self.pill = tk.Label(
            header, text="", font=self.fonts["bold"], fg="#ffffff", bg=IDLE, padx=14, pady=6,
        )
        self.pill.pack(side="right", anchor="center")

        self._build_top(page)

        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)
        server = ttk.Frame(notebook, style="Card.TFrame", padding=22)
        client = ttk.Frame(notebook, style="Card.TFrame", padding=22)
        notebook.add(server, text="Serveur : mon clavier et ma souris contrôlent les autres")
        notebook.add(client, text="Client : mon PC est contrôlé par un autre")
        self._build_server(server)
        self._build_client(client)

    def _build_top(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(20, 16))
        card.pack(fill="x", pady=(18, 14))

        left = ttk.Frame(card, style="Card.TFrame")
        left.pack(side="left")
        ttk.Label(left, text="Mot de passe commun", style="Card.TLabel", font=self.fonts["bold"]).pack(
            anchor="w"
        )
        ttk.Entry(left, textvariable=self.password, show="•", width=30).pack(anchor="w", pady=(6, 0))
        ttk.Label(left, text="Le même sur tous les ordinateurs", style="Muted.TLabel").pack(
            anchor="w", pady=(4, 0)
        )

        right = ttk.Frame(card, style="Card.TFrame")
        right.pack(side="right", anchor="e")
        ttk.Label(right, text="Ce PC", style="Muted.TLabel").pack(anchor="e")
        ttk.Label(right, text=self.master_name, style="Heading.TLabel").pack(anchor="e")
        ttk.Label(
            right, text=f"{self.screen_w} × {self.screen_h}", style="Muted.TLabel"
        ).pack(anchor="e")

    def _build_server(self, frame):
        self.port_var = tk.StringVar(value=str(self.config.get("port", DEFAULT_PORT)))

        controls = ttk.Frame(frame, style="Card.TFrame")
        controls.pack(fill="x")
        ttk.Label(controls, text="Port", style="Card.TLabel").pack(side="left")
        ttk.Entry(controls, textvariable=self.port_var, width=8).pack(side="left", padx=(8, 16))
        self.server_btn = ttk.Button(
            controls, text="Démarrer le serveur", style="Accent.TButton", command=self.toggle_server
        )
        self.server_btn.pack(side="left")

        address = ttk.Frame(frame, style="Card.TFrame")
        address.pack(fill="x", pady=(18, 0))
        ttk.Label(address, text="Adresse à saisir sur les autres PC", style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(address, style="Card.TFrame")
        row.pack(fill="x", pady=(2, 0))
        self.address_var = tk.StringVar(value=lan_address())
        ttk.Label(row, textvariable=self.address_var, style="Big.TLabel").pack(side="left")
        ttk.Button(row, text="Copier", command=self.copy_address).pack(side="left", padx=14)
        self.server_info = tk.StringVar(value="Démarrez le serveur pour que les autres PC puissent se connecter.")
        ttk.Label(address, textvariable=self.server_info, style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        ttk.Separator(frame).pack(fill="x", pady=18)

        ttk.Label(frame, text="Disposition des écrans", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Glissez les écrans pour les placer comme sur votre bureau. "
                 "Le curseur passe d'un écran à l'autre par le bord collé.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        self.canvas = tk.Canvas(
            frame, height=250, bg=CANVAS_BG, highlightthickness=1,
            highlightbackground=BORDER, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        bottom = ttk.Frame(frame, style="Card.TFrame")
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="Retirer l'écran sélectionné", command=self.remove_selected).pack(side="left")
        ttk.Label(bottom, text="Cliquez sur un écran pour le sélectionner", style="Muted.TLabel").pack(
            side="right"
        )

    def _build_client(self, frame):
        self.host_var = tk.StringVar(value=self.config.get("host", ""))
        self.client_port_var = tk.StringVar(value=str(self.config.get("client_port", DEFAULT_PORT)))
        self.client_name_var = tk.StringVar(value=self.config.get("client_name", self.master_name))

        ttk.Label(frame, text="Connecter ce PC à un serveur", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Le serveur doit être démarré sur l'autre PC. Son adresse est affichée dans l'onglet Serveur.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        form = ttk.Frame(frame, style="Card.TFrame")
        form.pack(fill="x")
        form.columnconfigure(0, weight=3)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Adresse IP du serveur", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text="Port", style="Card.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Entry(form, textvariable=self.host_var).grid(row=1, column=0, sticky="ew", pady=(4, 14))
        ttk.Entry(form, textvariable=self.client_port_var).grid(
            row=1, column=1, sticky="ew", padx=(14, 0), pady=(4, 14)
        )
        ttk.Label(form, text="Nom de ce PC (affiché sur le serveur)", style="Card.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )
        ttk.Entry(form, textvariable=self.client_name_var).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        self.client_btn = ttk.Button(frame, text="Connecter", style="Accent.TButton", command=self.toggle_client)
        self.client_btn.pack(anchor="w", pady=(22, 0))

    # --- serveur ---------------------------------------------------------

    def _notify(self, message):
        """Appelable depuis n'importe quel thread."""
        self.events.put(lambda: self.status.set(message))

    def copy_address(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.address_var.get())
        self.status.set("Adresse copiée dans le presse-papiers.")

    def toggle_server(self):
        if self.hub is not None:
            self.hub.stop()
            self.hub = None
            self.server_btn.config(text="Démarrer le serveur", style="Accent.TButton")
            self.server_info.set("Démarrez le serveur pour que les autres PC puissent se connecter.")
            self._draw()
            return

        password = self.password.get()
        if not password:
            messagebox.showwarning("SoftKVM", "Saisissez un mot de passe commun.", parent=self.root)
            return
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showwarning("SoftKVM", "Le port doit être un nombre.", parent=self.root)
            return

        hub = Hub(
            self.layout,
            self.layout_lock,
            password,
            self.master_name,
            (self.screen_w, self.screen_h),
            lambda h: PynputCapture(h),
            notify=self._notify,
        )
        try:
            hub.start(port=port)
        except OSError as exc:
            messagebox.showerror(
                "SoftKVM", f"Impossible de démarrer le serveur : {exc}", parent=self.root
            )
            return
        self.hub = hub
        self.server_btn.config(text="Arrêter le serveur", style="Danger.TButton")
        self.server_info.set(f"Port {hub.port} : saisissez cette adresse et ce port sur les autres PC.")
        self._save_settings()

    def remove_selected(self):
        name = self._selected
        if not name or name == self.master_name:
            return
        with self.layout_lock:
            self.layout.screens.pop(name, None)
        self._selected = None
        self._draw()

    # --- client ----------------------------------------------------------

    def toggle_client(self):
        if self._connecting:
            return
        if self.client is not None:
            self.client.close()
            self.client = None
            self._update_client_button()
            return

        host = self.host_var.get().strip()
        password = self.password.get()
        if not host or not password:
            messagebox.showwarning(
                "SoftKVM", "Saisissez l'adresse du serveur et le mot de passe.", parent=self.root
            )
            return
        try:
            port = int(self.client_port_var.get())
        except ValueError:
            messagebox.showwarning("SoftKVM", "Le port doit être un nombre.", parent=self.root)
            return
        name = self.client_name_var.get().strip() or self.master_name

        client = Client(
            host, port, password, name, (self.screen_w, self.screen_h),
            PynputInjector(), notify=self._notify,
        )
        self.client = client
        self._connecting = True
        self._update_client_button()
        self._save_settings()
        threading.Thread(target=self._connect_worker, args=(client,), name="connect", daemon=True).start()

    def _connect_worker(self, client):
        try:
            client.connect()
        except OSError as exc:
            self.events.put(lambda: self._connect_failed(client, exc))
            return
        self.events.put(self._connect_done)

    def _connect_done(self):
        self._connecting = False
        self._update_client_button()

    def _connect_failed(self, client, exc):
        if self.client is client:
            self.client = None
        self._connecting = False
        self._update_client_button()
        self.status.set(f"Connexion impossible : {exc}")

    def _update_client_button(self):
        if self._connecting:
            text, state, style = "Connexion…", "disabled", "Accent.TButton"
        elif self.client is not None:
            text, state, style = "Déconnecter", "normal", "Danger.TButton"
        else:
            text, state, style = "Connecter", "normal", "Accent.TButton"
        self.client_btn.config(text=text, state=state, style=style)

    # --- pastille d'état -------------------------------------------------

    def _refresh_pill(self):
        if self.hub is not None:
            count = len(self.hub.connected())
            if count == 0:
                text = "Serveur actif · aucun PC connecté"
            elif count == 1:
                text = "Serveur actif · 1 PC connecté"
            else:
                text = f"Serveur actif · {count} PC connectés"
            color = SUCCESS
        elif self.client is not None and self.client.connected:
            text, color = "Connecté au serveur", SUCCESS
        elif self._connecting:
            text, color = "Connexion en cours…", WARNING
        else:
            text, color = "Inactif", IDLE
        if self.pill.cget("text") != text:
            self.pill.config(text=text, bg=color)

    # --- boucle de l'interface -------------------------------------------

    def _pump(self):
        while True:
            try:
                action = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                action()
            except Exception:  # noqa: BLE001 - une erreur d'affichage ne doit pas tuer la boucle
                log.exception("erreur dans l'interface")
        if self.client is not None and not self.client.connected and not self._connecting:
            self.client = None
        self._update_client_button()
        self._refresh_pill()
        self._save_layout_if_changed()
        self._draw()
        self.root.after(300, self._pump)

    def _save_settings(self):
        self.config.update(
            password=self.password.get(),
            port=self.port_var.get(),
            host=self.host_var.get().strip(),
            client_port=self.client_port_var.get(),
            client_name=self.client_name_var.get().strip(),
        )
        save_config(self.config)

    def _save_layout_if_changed(self):
        with self.layout_lock:
            data = self.layout.to_dict()
        if data != self._saved_layout:
            self._saved_layout = data
            self.config["layout"] = data
            save_config(self.config)

    def on_close(self):
        if self.hub is not None:
            self.hub.stop()
            self.hub = None
        if self.client is not None:
            self.client.close()
            self.client = None
        self._save_settings()
        self._save_layout_if_changed()
        self.root.destroy()

    # --- dessin de la disposition ----------------------------------------

    def _compute_view(self, rects, cw, ch):
        minx = min(r.x for r in rects.values())
        miny = min(r.y for r in rects.values())
        maxx = max(r.x + r.w for r in rects.values())
        maxy = max(r.y + r.h for r in rects.values())
        scale = min(
            (cw - 2 * MARGIN) / max(maxx - minx, 1),
            (ch - 2 * MARGIN) / max(maxy - miny, 1),
        )
        return minx, miny, scale, MARGIN

    def _to_canvas(self, x, y):
        minx, miny, scale, margin = self._view
        return margin + (x - minx) * scale, margin + (y - miny) * scale

    def _to_layout(self, cx, cy):
        minx, miny, scale, margin = self._view
        return minx + (cx - margin) / scale, miny + (cy - margin) / scale

    def _draw(self):
        canvas = self.canvas
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 50 or ch < 50:
            return
        with self.layout_lock:
            rects = {n: Rect(r.x, r.y, r.w, r.h) for n, r in self.layout.screens.items()}
        if not rects:
            return
        if self._drag is None or self._view is None:
            self._view = self._compute_view(rects, cw, ch)

        connected = set(self.hub.connected()) if self.hub is not None else set()
        active = self.hub.active if self.hub is not None else None

        canvas.delete("all")
        self._hit = {}
        for name in sorted(rects):
            rect = rects[name]
            x0, y0 = self._to_canvas(rect.x, rect.y)
            x1, y1 = self._to_canvas(rect.x + rect.w, rect.y + rect.h)
            if name == active:
                kind = "active"
            elif name == self.master_name:
                kind = "master"
            elif name in connected:
                kind = "connected"
            else:
                kind = "offline"
            fill, outline = SCREEN_COLORS[kind]
            selected = name == self._selected
            _round_rect(
                canvas, x0, y0, x1, y1, 12,
                fill=fill,
                outline=TEXT if selected else outline,
                width=3 if selected else 2,
            )
            if kind == "master":
                status = "ce PC"
            elif kind == "connected":
                status = "connecté"
            elif kind == "active":
                status = "contrôlé à distance"
            else:
                status = "hors ligne"
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            wrap = max(x1 - x0 - 16, 40)
            if x1 - x0 >= 90 and y1 - y0 >= 50:
                canvas.create_text(
                    cx, cy - 10, text=name, font=self.fonts["bold"], fill=TEXT,
                    width=wrap, justify="center",
                )
                canvas.create_text(
                    cx, cy + 10, text=f"{rect.w}×{rect.h} · {status}",
                    font=self.fonts["small"], fill=MUTED, width=wrap, justify="center",
                )
            self._hit[name] = (x0, y0, x1, y1)

    def _on_press(self, event):
        if self._view is None:
            return
        self._selected = None
        for name, (x0, y0, x1, y1) in self._hit.items():
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                with self.layout_lock:
                    rect = self.layout.screens[name]
                    rx, ry = rect.x, rect.y
                lx, ly = self._to_layout(event.x, event.y)
                self._drag = (name, lx - rx, ly - ry)
                self._selected = name
                break
        self._draw()

    def _on_motion(self, event):
        if self._drag is None or self._view is None:
            return
        name, ox, oy = self._drag
        lx, ly = self._to_layout(event.x, event.y)
        with self.layout_lock:
            self.layout.move(name, round(lx - ox), round(ly - oy))
        self._draw()

    def _on_release(self, event):
        if self._drag is None:
            return
        name, _, _ = self._drag
        self._drag = None
        with self.layout_lock:
            rect = self.layout.screens[name]
            x, y = self.layout.snap(name, rect.x, rect.y)
            self.layout.move(name, x, y)
        self._draw()
