"""LCS-Resources: tiny always-on-top CPU / GPU / RAM overlay (LionClad Studios).

Drag to move. Mouse wheel = opacity. Right-click = menu. Ctrl+Shift+M = show/hide.
Run with pythonw.exe so no console window appears.
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from ctypes import wintypes

import psutil

try:
    import pynvml
    pynvml.nvmlInit()
    _GPU = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:
    pynvml = None
    _GPU = None

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
LOG = os.path.join(HERE, "lcs_resources.log")
STARTUP_LNK = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup\LCS-Resources.lnk",
)
DEFAULTS = {"x": None, "y": 40, "opacity": 0.85, "visible": True, "refresh_ms": 1000}
HOTKEY_ID = 1
MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000
VK_M = 0x4D
WM_HOTKEY = 0x0312

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        tmp = CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG)
    except OSError as e:
        log(f"save_config failed: {e}")


def color_for(pct):
    if pct is None:
        return "#8a8a8a"
    if pct < 50:
        return "#9be59b"
    if pct < 80:
        return "#ffd166"
    return "#ff6b6b"


class App:
    def __init__(self):
        self.cfg = load_config()
        self.hotkey_flag = threading.Event()
        self.hotkey_ok = None  # set by hotkey thread
        self.save_job = None

        self.root = tk.Tk()
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", float(self.cfg["opacity"]))
        r.configure(bg="#14161a", highlightthickness=1, highlightbackground="#3a3f47")

        self.rows = {}
        font = ("Consolas", 11, "bold")
        for name in ("CPU", "GPU", "RAM"):
            lbl = tk.Label(r, text=f"{name}   --%", font=font, fg="#9be59b",
                           bg="#14161a", anchor="w", padx=8, pady=1)
            lbl.pack(fill="x")
            self.rows[name] = lbl
        self.warn = tk.Label(r, text="", font=("Consolas", 8), fg="#ff6b6b",
                             bg="#14161a", anchor="w", padx=8)

        self._drag = None
        self.autostart_var = tk.BooleanVar(value=os.path.exists(STARTUP_LNK))
        self.menu = self._build_menu()
        for w in (r, *self.rows.values(), self.warn):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<MouseWheel>", self._wheel)
            w.bind("<Button-3>", self._popup)

        r.update_idletasks()
        self._place()
        psutil.cpu_percent(interval=None)  # prime the counter

        self.visible = bool(self.cfg["visible"])
        if not self.visible:
            r.withdraw()

        threading.Thread(target=self._hotkey_thread, daemon=True).start()
        r.after(150, self._poll_hotkey)
        if self.visible:
            self._tick()

    # ---- placement / persistence
    def _place(self):
        r = self.root
        w, h = r.winfo_reqwidth(), r.winfo_reqheight()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        x, y = self.cfg["x"], self.cfg["y"]
        if x is None:
            x = sw - w - 40
        x = max(0, min(int(x), sw - w))
        y = max(0, min(int(y), sh - h))
        r.geometry(f"+{x}+{y}")

    def _save_soon(self):
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(400, lambda: save_config(self.cfg))

    # ---- drag / opacity / menu
    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _drag_end(self, _e):
        self._drag = None
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        self._save_soon()

    def set_opacity(self, v):
        v = round(max(0.15, min(1.0, v)), 2)
        self.cfg["opacity"] = v
        self.root.attributes("-alpha", v)
        self._save_soon()

    def _wheel(self, e):
        self.set_opacity(self.cfg["opacity"] + (0.05 if e.delta > 0 else -0.05))

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        sub = tk.Menu(m, tearoff=0)
        for p in (25, 50, 75, 100):
            sub.add_command(label=f"{p}%", command=lambda p=p: self.set_opacity(p / 100))
        m.add_cascade(label="Opacity (wheel also works)", menu=sub)
        m.add_command(label="Reset position", command=self._reset_pos)
        m.add_checkbutton(label="Start with Windows", variable=self.autostart_var,
                          command=self._toggle_autostart)
        m.add_command(label="Hide  (Ctrl+Shift+M)", command=self.toggle)
        m.add_separator()
        m.add_command(label="Quit LCS-Resources", command=self.quit)
        return m

    def _popup(self, e):
        self.autostart_var.set(os.path.exists(STARTUP_LNK))
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _reset_pos(self):
        self.cfg["x"], self.cfg["y"] = None, 40
        self._place()
        self._save_soon()

    def _toggle_autostart(self):
        if self.autostart_var.get():
            exe = sys.executable
            if exe.lower().endswith("python.exe"):
                exe = exe[:-10] + "pythonw.exe"
            ps = (
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
                "$s.TargetPath='%s';$s.Arguments='\"%s\"';$s.WorkingDirectory='%s';"
                "$s.WindowStyle=7;$s.Save()" % (STARTUP_LNK, exe, os.path.join(HERE, "lcs_resources.py"), HERE)
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           creationflags=0x08000000, check=False)
        else:
            try:
                os.remove(STARTUP_LNK)
            except OSError:
                pass

    # ---- show/hide
    def toggle(self):
        if self.visible:
            self.root.withdraw()
            self.visible = False
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.visible = True
            psutil.cpu_percent(interval=None)
            self._tick()
        self.cfg["visible"] = self.visible
        save_config(self.cfg)

    def quit(self):
        save_config(self.cfg)
        self.root.destroy()

    # ---- hotkey (global, via RegisterHotKey)
    def _hotkey_thread(self):
        ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_M)
        self.hotkey_ok = bool(ok)
        if not ok:
            log(f"RegisterHotKey failed, error {kernel32.GetLastError()}")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.hotkey_flag.set()

    def _poll_hotkey(self):
        if self.hotkey_flag.is_set():
            self.hotkey_flag.clear()
            self.toggle()
        if self.hotkey_ok is False and not self.warn.winfo_ismapped():
            self.warn.config(text="hotkey in use")
            self.warn.pack(fill="x")
        self.root.after(150, self._poll_hotkey)

    # ---- sampling (only runs while visible)
    def _tick(self):
        if not self.visible:
            return
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        gpu = None
        if _GPU is not None:
            try:
                gpu = pynvml.nvmlDeviceGetUtilizationRates(_GPU).gpu
            except Exception:
                gpu = None
        for name, val in (("CPU", cpu), ("GPU", gpu), ("RAM", ram)):
            txt = f"{name}  {val:3.0f}%" if val is not None else f"{name}  n/a"
            self.rows[name].config(text=txt, fg=color_for(val))
        self.root.after(int(self.cfg["refresh_ms"]), self._tick)

    def run(self):
        self.root.mainloop()


def single_instance():
    h = kernel32.CreateMutexW(None, False, "Local\\LCS-Resources-Overlay")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return h


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    _mutex = single_instance()
    if _mutex is None:
        sys.exit(0)
    try:
        App().run()
    except Exception as exc:  # pythonw has no console; keep a trace
        log(f"fatal: {exc!r}")
        raise
