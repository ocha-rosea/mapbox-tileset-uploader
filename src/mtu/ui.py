"""Desktop UI for Mapbox Tileset Uploader."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import webbrowser
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from mtu.converters import get_supported_formats
from mtu.uploader import TilesetConfig, TilesetUploader, UploadResult


_SINGLE_INSTANCE_LOCK_FILE: object | None = None


@dataclass
class UIConfig:
    """Persisted settings for the desktop UI."""

    access_token: str = ""
    username: str = ""
    use_env_credentials: bool = True
    last_file_path: str = ""
    tileset_id: str = ""
    source_id: str = ""
    tileset_name: str = ""
    min_zoom: int = 0
    max_zoom: int = 10
    description: str = ""
    attribution: str = ""
    format_hint: str = ""
    capacity_guard_enabled: bool = False
    capacity_limit_mb: float = 0.0
    capacity_used_mb: float = 0.0


def get_config_path() -> Path:
    """Return the per-user config path."""
    return Path.home() / ".mtu" / "desktop_config.json"


def load_ui_config(config_path: Path | None = None) -> UIConfig:
    """Load UI settings from disk."""
    path = config_path or get_config_path()
    if not path.exists():
        return UIConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return UIConfig()

    defaults = asdict(UIConfig())
    safe_data = {k: data.get(k, v) for k, v in defaults.items()}

    return UIConfig(
        access_token=str(safe_data["access_token"]),
        username=str(safe_data["username"]),
        use_env_credentials=bool(safe_data["use_env_credentials"]),
        last_file_path=str(safe_data["last_file_path"]),
        tileset_id=str(safe_data["tileset_id"]),
        source_id=str(safe_data["source_id"]),
        tileset_name=str(safe_data["tileset_name"]),
        min_zoom=int(safe_data["min_zoom"]),
        max_zoom=int(safe_data["max_zoom"]),
        description=str(safe_data["description"]),
        attribution=str(safe_data["attribution"]),
        format_hint=str(safe_data["format_hint"]),
        capacity_guard_enabled=bool(safe_data["capacity_guard_enabled"]),
        capacity_limit_mb=float(safe_data["capacity_limit_mb"]),
        capacity_used_mb=float(safe_data["capacity_used_mb"]),
    )


def save_ui_config(config: UIConfig, config_path: Path | None = None) -> None:
    """Save UI settings to disk."""
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")


class MTUDesktopApp:
    """Tkinter desktop app for uploading GIS files to Mapbox."""

    PRIMARY_COLOR = "#009edb"
    SECONDARY_COLOR = "#999999"
    ACCENT_COLOR = "#f58220"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OCHA ROSEA Mapbox Tileset Uploader")
        self.root.geometry("980x760")
        self.root.minsize(920, 700)
        self.root.configure(bg="white")

        self._setup_styles()

        self.status_queue: Queue[tuple[str, str]] = Queue()
        self.upload_thread: threading.Thread | None = None

        self.config_path = get_config_path()
        self.saved = load_ui_config(self.config_path)

        self.file_path_var = tk.StringVar(value=self.saved.last_file_path)
        self.token_var = tk.StringVar(value=self.saved.access_token)
        self.username_var = tk.StringVar(value=self.saved.username)
        self.use_env_credentials_var = tk.BooleanVar(value=self.saved.use_env_credentials)
        self.tileset_name_var = tk.StringVar(value=self.saved.tileset_name)
        self.tileset_id_var = tk.StringVar(value=self.saved.tileset_id)
        self.source_id_var = tk.StringVar(value=self.saved.source_id)
        self.min_zoom_var = tk.StringVar(value=str(self.saved.min_zoom))
        self.max_zoom_var = tk.StringVar(value=str(self.saved.max_zoom))
        self.description_var = tk.StringVar(value=self.saved.description)
        self.attribution_var = tk.StringVar(value=self.saved.attribution)
        self.format_hint_var = tk.StringVar(value=self.saved.format_hint or "Auto-detect")
        self.capacity_guard_enabled_var = tk.BooleanVar(value=self.saved.capacity_guard_enabled)
        self.capacity_limit_mb_var = tk.StringVar(value=str(self.saved.capacity_limit_mb or ""))
        self.capacity_used_mb_var = tk.StringVar(value=str(self.saved.capacity_used_mb or ""))
        self.generated_tileset_id_var = tk.StringVar(value="")
        self.generated_source_id_var = tk.StringVar(value="")
        self.validate_var = tk.BooleanVar(value=True)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.preflight_started = False

        self.format_lookup = self._load_format_lookup()
        self._build_layout()
        self._refresh_generated_ids()
        self.preflight_ok = False
        self.root.after(200, self._poll_status_queue)

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background="white")
        style.configure(
            "App.TLabelframe",
            background="white",
            bordercolor=self.SECONDARY_COLOR,
            relief="solid",
        )
        style.configure(
            "App.TLabelframe.Label",
            background="white",
            foreground=self.PRIMARY_COLOR,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure("App.TLabel", background="white", foreground="#333333")
        style.configure("Primary.TButton", background=self.PRIMARY_COLOR, foreground="white")
        style.map(
            "Primary.TButton",
            background=[("active", self.ACCENT_COLOR), ("pressed", self.ACCENT_COLOR)],
            foreground=[("active", "white")],
        )
        style.configure("Accent.TButton", background=self.ACCENT_COLOR, foreground="white")
        style.map(
            "Accent.TButton",
            background=[("active", self.PRIMARY_COLOR), ("pressed", self.PRIMARY_COLOR)],
            foreground=[("active", "white")],
        )

    def _load_format_lookup(self) -> dict[str, str]:
        formats = {"Auto-detect": ""}
        for fmt in get_supported_formats():
            name = fmt["format_name"]
            formats[name] = name.lower()
        return formats

    def _build_layout(self) -> None:
        self.page_container = ttk.Frame(self.root, padding=12, style="App.TFrame")
        self.page_container.pack(fill=tk.BOTH, expand=True)

        self.intro_page = ttk.Frame(self.page_container, style="App.TFrame")
        self.main_page = ttk.Frame(self.page_container, style="App.TFrame")
        self._build_intro_page(self.intro_page)
        self.intro_page.pack(fill=tk.BOTH, expand=True)

        main_shell = ttk.Frame(self.main_page, style="App.TFrame")
        main_shell.pack(fill=tk.BOTH, expand=True)

        self.main_canvas = tk.Canvas(main_shell, background="white", highlightthickness=0)
        main_scrollbar = ttk.Scrollbar(main_shell, orient=tk.VERTICAL, command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=main_scrollbar.set)

        self.main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        main_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        container = ttk.Frame(self.main_canvas, style="App.TFrame")
        self.main_canvas_window = self.main_canvas.create_window((0, 0), window=container, anchor="nw")

        container.bind(
            "<Configure>",
            lambda _event: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all")),
        )
        self.main_canvas.bind(
            "<Configure>",
            lambda event: self.main_canvas.itemconfigure(self.main_canvas_window, width=event.width),
        )
        self.main_canvas.bind(
            "<Enter>",
            lambda _event: self.main_canvas.bind_all("<MouseWheel>", self._on_main_mousewheel),
        )
        self.main_canvas.bind(
            "<Leave>",
            lambda _event: self.main_canvas.unbind_all("<MouseWheel>"),
        )

        header = tk.Frame(container, bg=self.PRIMARY_COLOR, padx=12, pady=10)
        header.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            header,
            text="ROSEA MTU",
            bg=self.PRIMARY_COLOR,
            fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            header,
            text="OCHA ROSEA Mapbox Tileset Uploader",
            bg=self.PRIMARY_COLOR,
            fg=self.ACCENT_COLOR,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(14, 0))

        form_grid = ttk.Frame(container, style="App.TFrame")
        form_grid.pack(fill=tk.X)
        form_grid.columnconfigure(0, weight=1, uniform="maincols")
        form_grid.columnconfigure(1, weight=1, uniform="maincols")

        left_col = ttk.Frame(form_grid, style="App.TFrame")
        left_col.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 6))
        right_col = ttk.Frame(form_grid, style="App.TFrame")
        right_col.grid(row=0, column=1, sticky=tk.NSEW, padx=(6, 0))

        left_col.columnconfigure(0, weight=1)
        right_col.columnconfigure(0, weight=1)

        file_frame = ttk.LabelFrame(left_col, text="GIS Input", padding=10, style="App.TLabelframe")
        file_frame.pack(fill=tk.X)

        ttk.Label(file_frame, text="File", style="App.TLabel").grid(row=0, column=0, sticky=tk.W)
        file_entry = ttk.Entry(file_frame, textvariable=self.file_path_var, width=80)
        file_entry.grid(row=0, column=1, sticky=tk.EW, padx=(8, 8))
        ttk.Button(file_frame, text="Browse", command=self._select_file, style="Primary.TButton").grid(
            row=0, column=2, sticky=tk.E
        )

        ttk.Label(file_frame, text="Format", style="App.TLabel").grid(
            row=1, column=0, sticky=tk.W, pady=(8, 0)
        )
        format_combo = ttk.Combobox(
            file_frame,
            textvariable=self.format_hint_var,
            values=list(self.format_lookup.keys()),
            state="readonly",
            width=32,
        )
        format_combo.grid(row=1, column=1, sticky=tk.W, padx=(8, 8), pady=(8, 0))

        file_frame.columnconfigure(1, weight=1)

        creds_frame = ttk.LabelFrame(
            left_col, text="Mapbox Credentials", padding=10, style="App.TLabelframe"
        )
        creds_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(creds_frame, text="Access Token", style="App.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        self.token_entry = ttk.Entry(creds_frame, textvariable=self.token_var, show="*", width=70)
        self.token_entry.grid(
            row=0, column=1, sticky=tk.EW, padx=(8, 0)
        )

        ttk.Label(creds_frame, text="Username", style="App.TLabel").grid(
            row=1, column=0, sticky=tk.W, pady=(8, 0)
        )
        self.username_entry = ttk.Entry(creds_frame, textvariable=self.username_var, width=70)
        self.username_entry.grid(
            row=1, column=1, sticky=tk.EW, padx=(8, 0), pady=(8, 0)
        )

        ttk.Checkbutton(
            creds_frame,
            text="Read from env vars: MAPBOX_ACCESS_TOKEN + MAPBOX_USERNAME (recommended)",
            variable=self.use_env_credentials_var,
            command=self._on_credentials_mode_changed,
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        env_actions = ttk.Frame(creds_frame)
        env_actions.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        self.load_env_button = ttk.Button(
            env_actions, text="Load From Env", command=self._load_credentials_from_env
        )
        self.load_env_button.pack(
            side=tk.LEFT
        )
        self.save_env_button = ttk.Button(
            env_actions,
            text="Save to User Env",
            command=self._save_credentials_to_user_env,
        )
        self.save_env_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(
            creds_frame,
            text="Get Mapbox Token",
            command=self._open_token_page,
            style="Accent.TButton",
        ).grid(
            row=4, column=0, sticky=tk.W, pady=(10, 0)
        )
        ttk.Button(
            creds_frame,
            text="Save Config",
            command=self._save_current_config,
            style="Primary.TButton",
        ).grid(
            row=4, column=1, sticky=tk.E, pady=(10, 0)
        )
        creds_frame.columnconfigure(1, weight=1)
        self._on_credentials_mode_changed()

        settings_frame = ttk.LabelFrame(
            right_col, text="Tileset Settings", padding=10, style="App.TLabelframe"
        )
        settings_frame.pack(fill=tk.X, pady=(10, 0))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)

        ttk.Label(settings_frame, text="Final Tileset Name", style="App.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(settings_frame, textvariable=self.tileset_name_var).grid(
            row=0, column=1, columnspan=3, sticky=tk.EW, padx=(8, 0)
        )

        ttk.Label(settings_frame, text="Tileset ID (auto, editable)", style="App.TLabel").grid(
            row=1, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(
            settings_frame,
            textvariable=self.tileset_id_var,
        ).grid(row=1, column=1, sticky=tk.EW, padx=(8, 8), pady=(8, 0))

        ttk.Button(
            settings_frame,
            text="Regenerate IDs",
            command=self._on_tileset_name_changed,
            style="Accent.TButton",
        ).grid(row=1, column=3, sticky=tk.E, pady=(8, 0))

        ttk.Label(settings_frame, text="Source ID (auto, editable)", style="App.TLabel").grid(
            row=2, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(
            settings_frame,
            textvariable=self.source_id_var,
        ).grid(row=2, column=1, columnspan=3, sticky=tk.EW, padx=(8, 0), pady=(8, 0))

        ttk.Label(settings_frame, text="Min Zoom", style="App.TLabel").grid(
            row=3, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Spinbox(
            settings_frame,
            textvariable=self.min_zoom_var,
            from_=0,
            to=22,
            width=8,
        ).grid(row=3, column=1, sticky=tk.W, padx=(8, 20), pady=(8, 0))

        ttk.Label(settings_frame, text="Max Zoom", style="App.TLabel").grid(
            row=3, column=2, sticky=tk.W, pady=(8, 0)
        )
        ttk.Spinbox(
            settings_frame,
            textvariable=self.max_zoom_var,
            from_=0,
            to=22,
            width=8,
        ).grid(row=3, column=3, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        ttk.Label(settings_frame, text="Description", style="App.TLabel").grid(
            row=4, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(settings_frame, textvariable=self.description_var).grid(
            row=4, column=1, columnspan=3, sticky=tk.EW, padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(settings_frame, text="Attribution", style="App.TLabel").grid(
            row=5, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(settings_frame, textvariable=self.attribution_var).grid(
            row=5, column=1, columnspan=3, sticky=tk.EW, padx=(8, 0), pady=(8, 0)
        )

        ttk.Checkbutton(
            settings_frame,
            text="Validate geometry before upload",
            variable=self.validate_var,
        ).grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))

        ttk.Checkbutton(
            settings_frame,
            text="Dry run (validate only)",
            variable=self.dry_run_var,
        ).grid(row=6, column=2, columnspan=2, sticky=tk.W, pady=(10, 0))

        limits_frame = ttk.LabelFrame(
            left_col, text="Mapbox Limits & Capacity", padding=10, style="App.TLabelframe"
        )
        limits_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(
            limits_frame,
            text=(
                "Mapbox zoom range is typically 0-22. This app defaults to min 0 and max 10. "
                "Capacity and costs vary by plan; exceeding plan usage may incur additional charges."
            ),
            style="App.TLabel",
            wraplength=420,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W)

        ttk.Checkbutton(
            limits_frame,
            text="Enable capacity guard (block upload when projected usage exceeds your configured plan limit)",
            variable=self.capacity_guard_enabled_var,
        ).grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))

        ttk.Label(limits_frame, text="Plan Capacity (MB)", style="App.TLabel").grid(
            row=2, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(limits_frame, textvariable=self.capacity_limit_mb_var, width=16).grid(
            row=2, column=1, sticky=tk.W, padx=(8, 20), pady=(8, 0)
        )

        ttk.Label(limits_frame, text="Currently Used (MB)", style="App.TLabel").grid(
            row=2, column=2, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(limits_frame, textvariable=self.capacity_used_mb_var, width=16).grid(
            row=2, column=3, sticky=tk.W, padx=(8, 0), pady=(8, 0)
        )

        ttk.Button(
            limits_frame,
            text="Open Mapbox Pricing",
            command=self._open_pricing_page,
            style="Accent.TButton",
        ).grid(row=3, column=3, sticky=tk.E, pady=(10, 0))

        actions = ttk.Frame(right_col)
        actions.pack(fill=tk.X, pady=(10, 0))
        self.upload_button = ttk.Button(
            actions,
            text="Upload to Mapbox",
            command=self._start_upload,
            style="Primary.TButton",
        )
        self.upload_button.pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(container, text="Status", padding=10, style="App.TLabelframe")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_text = tk.Text(log_frame, height=12, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(background="#f8fbfd", foreground="#333333")
        self.log_text.configure(state=tk.DISABLED)

    def _on_main_mousewheel(self, event: tk.Event) -> None:
        self.main_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _build_intro_page(self, parent: ttk.Frame) -> None:
        top_band = tk.Frame(parent, bg=self.PRIMARY_COLOR, padx=14, pady=12)
        top_band.pack(fill=tk.X)
        tk.Label(
            top_band,
            text="Welcome to OCHA ROSEA Mapbox Tileset Uploader",
            bg=self.PRIMARY_COLOR,
            fg="white",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")

        body = tk.Frame(parent, bg="white", padx=16, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        info_text = (
            "This tool converts GIS files (GeoJSON, Shapefile ZIP, and more) and uploads them to "
            "Mapbox as tilesets.\n\n"
            "How it works:\n"
            "1) Choose a GIS file\n"
            "2) Set Mapbox credentials (or use MAPBOX_ACCESS_TOKEN / MAPBOX_USERNAME)\n"
            "3) Review tileset settings\n"
            "4) Upload and monitor live progress\n\n"
            "Mapbox notes:\n"
            "- Zoom range is typically 0-22; app defaults to 0-10\n"
            "- Capacity and cost depend on your Mapbox plan\n"
            "- Exceeding plan usage may incur additional charges\n\n"
            "Developed by OCHA ROSEA."
        )

        tk.Label(
            body,
            text=info_text,
            justify=tk.LEFT,
            bg="white",
            fg="#333333",
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        actions = tk.Frame(body, bg="white")
        actions.pack(fill=tk.X, pady=(18, 0))
        tk.Button(
            actions,
            text="Start",
            bg=self.ACCENT_COLOR,
            fg="white",
            activebackground=self.PRIMARY_COLOR,
            activeforeground="white",
            relief=tk.FLAT,
            padx=16,
            pady=7,
            command=self._start_main_page,
        ).pack(side=tk.RIGHT)

    def _start_main_page(self) -> None:
        self.intro_page.pack_forget()
        self.main_page.pack(fill=tk.BOTH, expand=True)
        if not self.preflight_started:
            self.preflight_started = True
            self.preflight_ok = self._run_preflight_checks(show_dialog=True)

    def _select_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select GIS file",
            filetypes=[
                ("GIS files", "*.geojson *.json *.zip *.shp *.topojson *.gpkg *.kml *.kmz *.fgb *.parquet *.geoparquet *.gpx"),
                ("GeoJSON", "*.geojson *.json"),
                ("Shapefile ZIP", "*.zip"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.file_path_var.set(path)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _save_current_config(self) -> None:
        if self.use_env_credentials_var.get():
            token_for_config = ""
        else:
            token_for_config = self.token_var.get().strip()

        config = UIConfig(
            access_token=token_for_config,
            username=self.username_var.get().strip(),
            use_env_credentials=self.use_env_credentials_var.get(),
            last_file_path=self.file_path_var.get().strip(),
            tileset_id=self.tileset_id_var.get().strip(),
            source_id=self.source_id_var.get().strip(),
            tileset_name=self.tileset_name_var.get().strip(),
            min_zoom=self._safe_int(self.min_zoom_var.get(), 0),
            max_zoom=self._safe_int(self.max_zoom_var.get(), 10),
            description=self.description_var.get().strip(),
            attribution=self.attribution_var.get().strip(),
            format_hint=self.format_hint_var.get().strip(),
            capacity_guard_enabled=self.capacity_guard_enabled_var.get(),
            capacity_limit_mb=self._safe_float(self.capacity_limit_mb_var.get(), 0.0),
            capacity_used_mb=self._safe_float(self.capacity_used_mb_var.get(), 0.0),
        )

        try:
            save_ui_config(config, self.config_path)
        except OSError as exc:
            messagebox.showerror("Config Error", f"Could not save config: {exc}")
            return

        self._append_log(f"Saved settings to {self.config_path}")

    def _open_token_page(self) -> None:
        webbrowser.open("https://account.mapbox.com/access-tokens/")

    def _open_pricing_page(self) -> None:
        webbrowser.open("https://www.mapbox.com/pricing/")

    def _on_credentials_mode_changed(self) -> None:
        use_env = self.use_env_credentials_var.get()

        if use_env:
            self.token_entry.configure(state="disabled")
            self.username_entry.configure(state="disabled")
            self.save_env_button.configure(state="disabled")
        else:
            self.token_entry.configure(state="normal")
            self.username_entry.configure(state="normal")
            self.save_env_button.configure(state="normal")

        self.load_env_button.configure(state="normal")

    def _load_credentials_from_env(self) -> None:
        env_token = os.environ.get("MAPBOX_ACCESS_TOKEN", "")
        env_username = os.environ.get("MAPBOX_USERNAME", "")

        if env_token:
            self.token_var.set(env_token)
        if env_username:
            self.username_var.set(env_username)

        if env_token or env_username:
            self._append_log(
                "Loaded credentials from MAPBOX_ACCESS_TOKEN and MAPBOX_USERNAME."
            )
        else:
            messagebox.showinfo(
                "Environment Variables",
                "MAPBOX_ACCESS_TOKEN and MAPBOX_USERNAME are not set in this process.",
            )

    def _save_credentials_to_user_env(self) -> None:
        token = self.token_var.get().strip()
        username = self.username_var.get().strip()

        if not token:
            messagebox.showerror("Input Error", "Access token is required to save env variables.")
            return

        if not username:
            messagebox.showerror("Input Error", "Username is required to save env variables.")
            return

        try:
            subprocess.run(["setx", "MAPBOX_ACCESS_TOKEN", token], check=True, capture_output=True)
            subprocess.run(["setx", "MAPBOX_USERNAME", username], check=True, capture_output=True)
            self._append_log("Saved Mapbox credentials to user environment variables.")
            messagebox.showinfo(
                "Environment Saved",
                "Saved to user environment variables. Restart the app/terminal to pick them up.",
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="ignore")
            messagebox.showerror("Environment Save Error", stderr or str(exc))

    def _resolve_credentials(self) -> tuple[str, str]:
        if self.use_env_credentials_var.get():
            token = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()
            username = os.environ.get("MAPBOX_USERNAME", "").strip()
            return token, username

        return self.token_var.get().strip(), self.username_var.get().strip()

    def _on_tileset_name_changed(self, *_args: object) -> None:
        self._refresh_generated_ids()

    def _refresh_generated_ids(self) -> None:
        generated_tileset_id = TilesetUploader._generate_tileset_id(
            self.tileset_name_var.get().strip()
        )
        self.generated_tileset_id_var.set(generated_tileset_id)
        self.generated_source_id_var.set(generated_tileset_id.replace(".", "-"))
        self.tileset_id_var.set(generated_tileset_id)
        self.source_id_var.set(generated_tileset_id.replace(".", "-"))

    def _run_preflight_checks(self, show_dialog: bool) -> bool:
        self._append_log("Running preflight checks...")

        command = TilesetUploader.find_tilesets_command()
        has_inprocess = TilesetUploader.can_use_inprocess_tilesets()

        if not command and not has_inprocess:
            self._append_log("Preflight failed: 'tilesets' CLI not found.")
            self.upload_button.configure(state=tk.DISABLED)
            if show_dialog:
                messagebox.showwarning(
                    "Missing tilesets CLI",
                    "No usable mapbox-tilesets runtime was found. Install mapbox-tilesets and reopen the app.",
                )
            return False

        if not command and has_inprocess:
            self._append_log("Preflight OK: using in-process mapbox-tilesets module")
            self.upload_button.configure(state=tk.NORMAL)
            return True

        try:
            result = subprocess.run(
                command + ["--help"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except Exception as exc:
            self._append_log(f"Preflight failed: could not execute tilesets CLI ({exc}).")
            self.upload_button.configure(state=tk.DISABLED)
            if show_dialog:
                messagebox.showwarning(
                    "tilesets CLI error",
                    f"Could not run tilesets CLI: {exc}",
                )
            return False

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "unknown error"
            self._append_log(f"Preflight failed: tilesets CLI returned non-zero exit ({error_msg}).")
            self.upload_button.configure(state=tk.DISABLED)
            if show_dialog:
                messagebox.showwarning(
                    "tilesets CLI error",
                    f"tilesets CLI check failed: {error_msg}",
                )
            return False

        resolved_cmd = " ".join(command)
        self._append_log(f"Preflight OK: tilesets CLI available via: {resolved_cmd}")
        self.upload_button.configure(state=tk.NORMAL)
        return True

    @staticmethod
    def _safe_int(value: str, fallback: int) -> int:
        try:
            return int(value)
        except ValueError:
            return fallback

    @staticmethod
    def _safe_float(value: str, fallback: float) -> float:
        try:
            return float(value)
        except ValueError:
            return fallback

    def _validate_form(self) -> str | None:
        file_path = self.file_path_var.get().strip()
        if not file_path:
            return "Please choose a GIS file to upload."

        if not Path(file_path).exists():
            return "Selected file does not exist."

        token, username = self._resolve_credentials()

        if not token:
            return "Mapbox access token is required."

        if not username:
            return "Mapbox username is required."

        if not self.tileset_name_var.get().strip():
            return "Final tileset name is required."

        min_zoom = self._safe_int(self.min_zoom_var.get(), -1)
        max_zoom = self._safe_int(self.max_zoom_var.get(), -1)

        if min_zoom < 0 or min_zoom > 22:
            return "Min zoom must be between 0 and 22."

        if max_zoom < 0 or max_zoom > 22:
            return "Max zoom must be between 0 and 22."

        if min_zoom > max_zoom:
            return "Min zoom cannot be greater than max zoom."

        if self.capacity_guard_enabled_var.get():
            capacity = self._safe_float(self.capacity_limit_mb_var.get(), -1.0)
            used = self._safe_float(self.capacity_used_mb_var.get(), 0.0)

            if capacity <= 0:
                return "Plan Capacity (MB) must be greater than 0 when capacity guard is enabled."

            if used < 0:
                return "Currently Used (MB) cannot be negative."

            file_mb = Path(file_path).stat().st_size / (1024 * 1024)
            projected = used + file_mb
            if projected > capacity:
                return (
                    f"Capacity guard blocked upload: projected {projected:.1f} MB exceeds "
                    f"configured capacity {capacity:.1f} MB."
                )

        return None

    def _start_upload(self) -> None:
        if self.upload_thread and self.upload_thread.is_alive():
            return

        self.preflight_ok = self._run_preflight_checks(show_dialog=True)
        if not self.preflight_ok:
            return

        validation_error = self._validate_form()
        if validation_error:
            messagebox.showerror("Input Error", validation_error)
            return

        self._save_current_config()
        self.upload_button.configure(state=tk.DISABLED)
        self._append_log("Starting upload...")

        self.upload_thread = threading.Thread(target=self._run_upload, daemon=True)
        self.upload_thread.start()

    def _run_upload(self) -> None:
        try:
            tileset_id = self.tileset_id_var.get().strip()
            if not tileset_id:
                tileset_id = TilesetUploader._generate_tileset_id(self.tileset_name_var.get().strip())

            source_id = self.source_id_var.get().strip()
            if not source_id:
                source_id = tileset_id.replace(".", "-")

            config = TilesetConfig(
                tileset_id=tileset_id,
                tileset_name=self.tileset_name_var.get().strip(),
                source_id=source_id,
                min_zoom=self._safe_int(self.min_zoom_var.get(), 0),
                max_zoom=self._safe_int(self.max_zoom_var.get(), 10),
                description=self.description_var.get().strip(),
                attribution=self.attribution_var.get().strip(),
            )

            uploader = TilesetUploader(
                access_token=self._resolve_credentials()[0],
                username=self._resolve_credentials()[1],
                validate_geometry=self.validate_var.get(),
            )

            selected_format = self.format_lookup.get(self.format_hint_var.get().strip(), "")
            format_hint = selected_format or None

            self.status_queue.put(("log", f"Uploading file: {self.file_path_var.get().strip()}"))
            self.status_queue.put(("log", f"Final tileset name: {config.tileset_name}"))
            if self.use_env_credentials_var.get():
                self.status_queue.put(
                    (
                        "log",
                        "Credentials source: MAPBOX_ACCESS_TOKEN + MAPBOX_USERNAME",
                    )
                )
            else:
                self.status_queue.put(("log", "Credentials source: app form values"))
            self.status_queue.put(
                (
                    "log",
                    f"Tileset ID: {self._resolve_credentials()[1]}.{config.tileset_id}",
                )
            )
            self.status_queue.put(("log", f"Source ID: {config.source_id}"))
            self.status_queue.put(("log", f"Zoom levels: {config.min_zoom}-{config.max_zoom}"))
            if self.capacity_guard_enabled_var.get():
                capacity = self._safe_float(self.capacity_limit_mb_var.get(), 0.0)
                used = self._safe_float(self.capacity_used_mb_var.get(), 0.0)
                file_mb = Path(self.file_path_var.get().strip()).stat().st_size / (1024 * 1024)
                self.status_queue.put(
                    (
                        "log",
                        (
                            "Capacity guard: "
                            f"used {used:.1f} MB + file {file_mb:.1f} MB / cap {capacity:.1f} MB"
                        ),
                    )
                )

            result = uploader.upload_from_file(
                file_path=self.file_path_var.get().strip(),
                config=config,
                format_hint=format_hint,
                dry_run=self.dry_run_var.get(),
                progress_callback=self._on_upload_progress,
            )

            self._report_result(result)

        except Exception as exc:
            self.status_queue.put(("error", f"Upload failed: {exc}"))
        finally:
            self.status_queue.put(("done", ""))

    def _on_upload_progress(self, payload: dict[str, object]) -> None:
        percent = payload.get("percent")
        message = str(payload.get("message", ""))

        if isinstance(percent, int):
            line = f"[{percent:>3}%] {message}"
        else:
            line = message

        self.status_queue.put(("log", line))

    def _report_result(self, result: UploadResult) -> None:
        if result.conversion_result:
            self.status_queue.put(
                ("log", f"Detected format: {result.conversion_result.source_format}")
            )
            self.status_queue.put(("log", f"Features: {result.conversion_result.feature_count}"))

        if result.warnings:
            self.status_queue.put(("log", f"Warnings: {len(result.warnings)}"))
            for warning in result.warnings[:25]:
                self.status_queue.put(("log", f"  - {warning}"))
            if len(result.warnings) > 25:
                self.status_queue.put(("log", f"  ... and {len(result.warnings) - 25} more"))

        if result.success:
            self.status_queue.put(("log", "Upload successful."))
            self.status_queue.put(("log", f"Final tileset name: {self.tileset_name_var.get().strip()}"))
            self.status_queue.put(("log", f"Tileset ID: {result.tileset_id}"))
            if not result.dry_run:
                self.status_queue.put(
                    ("log", f"Mapbox Studio: https://studio.mapbox.com/tilesets/{result.tileset_id}/")
                )
        else:
            detail = result.error or "Unknown error from upload process."
            self.status_queue.put(("error", f"Upload failed: {detail}"))

    def _poll_status_queue(self) -> None:
        while True:
            try:
                level, message = self.status_queue.get_nowait()
            except Empty:
                break

            if level == "log":
                self._append_log(message)
            elif level == "error":
                self._append_log(message)
                messagebox.showerror("Upload Error", message)
            elif level == "done":
                self.upload_button.configure(state=tk.NORMAL)

        self.root.after(200, self._poll_status_queue)


def launch_ui() -> None:
    """Launch the desktop UI."""
    global _SINGLE_INSTANCE_LOCK_FILE

    if os.name == "nt":
        import msvcrt

        lock_path = Path(tempfile.gettempdir()) / "rosea_mtu_single_instance.lock"
        lock_file = open(lock_path, "a+b")

        try:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_file.close()
            return

        _SINGLE_INSTANCE_LOCK_FILE = lock_file

    root = tk.Tk()
    MTUDesktopApp(root)
    root.mainloop()
