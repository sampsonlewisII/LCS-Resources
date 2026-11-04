"""LCS-Resources: tiny always-on-top CPU / GPU / VRAM / GPU temp / RAM / network overlay.

Drag to move. Mouse wheel = opacity. Right-click = menu (Show submenu toggles each row).
Ctrl+Shift+M = show/hide.
Run with pythonw.exe so no console window appears.
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
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
ROW_ORDER = ("CPU", "GPU", "VRAM", "TEMP", "RAM", "NET", "FPS")
ROW_LABELS = {"CPU": "CPU", "GPU": "GPU", "VRAM": "VRAM", "TEMP": "GPU temp (F)",
              "RAM": "RAM", "NET": "Network", "FPS": "FPS (needs PresentMon)"}
DEFAULTS = {"x": None, "y": 40, "opacity": 0.85, "visible": True, "refresh_ms": 1000,
            "presentmon_path": "", "rows": {k: True for k in ROW_ORDER}}
NET_COLOR = "#9ecbff"
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
    rows = cfg.get("rows") if isinstance(cfg.get("rows"), dict) else {}
    cfg["rows"] = {k: bool(rows.get(k, True)) for k in ROW_ORDER}
    if not any(cfg["rows"].values()):
        cfg["rows"]["CPU"] = True
    return cfg


def save_config(cfg):
    try:
        tmp = CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG)
    except OSError as e:
        log(f"save_config failed: {e}")


def color_for(val, warn=50, hot=80):
    if val is None:
        return "#8a8a8a"
    if val < warn:
        return "#9be59b"
    if val < hot:
        return "#ffd166"
    return "#ff6b6b"


def fps_color(fps):
    if fps is None:
        return "#8a8a8a"
    if fps < 30:
        return "#ff6b6b"
    if fps < 60:
        return "#ffd166"
    return "#9be59b"


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def foreground_pid():
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def make_kill_job():
    """A Windows job object that kills its processes when this app dies, so the
    PresentMon helper can never be left running if the overlay is force-killed."""
    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IOC(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]

    class EXT(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    info = EXT()
    info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
    return job


class FpsMeter:
    """Foreground-app FPS from Intel's PresentMon (reads Windows' own present events;
    nothing is injected into any game). Runs only while the FPS row is on and visible."""
    SESSION = "LCS-Resources"

    def __init__(self, exe):
        self.exe = exe
        self.proc = None
        self.frames = {}  # pid -> deque of PresentMon frame times (seconds), last 1 s
        self.last_seen = {}  # pid -> when we last received a frame from it
        self.lock = threading.Lock()
        self.job = None
        self._kids, self._kids_for, self._kids_at = [], None, 0.0

    def available(self):
        return bool(self.exe) and os.path.exists(self.exe)

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running() or not self.available():
            return
        with self.lock:
            self.frames.clear()
            self.last_seen.clear()
        try:
            self.proc = subprocess.Popen(
                [self.exe, "--output_stdout", "--no_console_stats", "--v1_metrics",
                 "--exclude_dropped", "--session_name", self.SESSION, "--stop_existing_session"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=0x08000000)  # CREATE_NO_WINDOW
        except OSError as e:
            log(f"PresentMon start failed: {e}")
            self.proc = None
            return
        try:
            if self.job is None:
                self.job = make_kill_job()
            kernel32.AssignProcessToJobObject(wintypes.HANDLE(self.job), wintypes.HANDLE(int(self.proc._handle)))
        except Exception as e:
            log(f"job assign failed: {e}")
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def stop(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:  # ask PresentMon to end its trace session cleanly, then make sure it's gone
            subprocess.run([self.exe, "--terminate_existing_session", "--session_name", self.SESSION],
                           creationflags=0x08000000, timeout=5, capture_output=True)
        except Exception as e:
            log(f"PresentMon stop failed: {e}")
        if proc.poll() is None:
            proc.terminate()
        with self.lock:
            self.frames.clear()
            self.last_seen.clear()

    def _reader(self, proc):
        seen_header = False
        for raw in proc.stdout:
            line = raw.decode("utf-8", "ignore")
            if not seen_header:
                seen_header = line.startswith("Application,")
                continue
            parts = line.split(",")
            try:
                pid = int(parts[1])
                if parts[6].strip() == "1":  # dropped frame, never shown
                    continue
                t = float(parts[7])  # PresentMon's own frame timestamp (immune to pipe buffering)
            except (IndexError, ValueError):
                continue
            if proc is not self.proc:
                return
            with self.lock:
                dq = self.frames.setdefault(pid, deque())
                dq.append(t)
                while dq[0] < t - 1.0:  # keep one second of frames per process
                    dq.popleft()
                self.last_seen[pid] = time.monotonic()

    def _count(self, pids):
        """Average FPS over the last second of frames: (frames - 1) / time span."""
        now = time.monotonic()
        best = 0.0
        with self.lock:
            for p in list(self.frames):
                if now - self.last_seen.get(p, 0) > 2.0:  # stopped presenting
                    del self.frames[p]
                    self.last_seen.pop(p, None)
            for p in pids:
                dq = self.frames.get(p)
                if dq and len(dq) >= 2 and dq[-1] > dq[0]:
                    best = max(best, (len(dq) - 1) / (dq[-1] - dq[0]))
        return round(best) or None

    def fps_for(self, pid):
        """Frames per second of the foreground app: its own process first, then its
        child processes (browsers and launchers often present from a child)."""
        fps = self._count((pid,))
        if fps is None and pid:
            now = time.monotonic()
            if self._kids_for != pid or now - self._kids_at > 5.0:  # process-tree walk is the costly part
                try:
                    self._kids = [c.pid for c in psutil.Process(pid).children(recursive=True)]
                except psutil.Error:
                    self._kids = []
                self._kids_for, self._kids_at = pid, now
            fps = self._count(self._kids) if self._kids else None
        return fps


def fmt_speed(bps):
    if bps >= 1e8:
        return f"{bps / 1e6:.0f}M"
    if bps >= 1e6:
        return f"{bps / 1e6:.1f}M"
    return f"{bps / 1e3:.0f}K"


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
        for name in ROW_ORDER:
            self.rows[name] = tk.Label(r, text=f"{name:<4} --", font=font, fg="#9be59b",
                                       bg="#14161a", anchor="w", padx=8, pady=1, width=17)
        self.warn = tk.Label(r, text="", font=("Consolas", 8), fg="#ff6b6b",
                             bg="#14161a", anchor="w", padx=8)
        self._net_prev = None  # (time, bytes_recv, bytes_sent)
        pm = self.cfg.get("presentmon_path") or next(
            (p for p in (os.path.join(HERE, "bin", "PresentMon.exe"), os.path.join(HERE, "PresentMon.exe"))
             if os.path.exists(p)), "")
        self.fps = FpsMeter(pm)
        self.visible = bool(self.cfg["visible"])

        self._drag = None
        self.autostart_var = tk.BooleanVar(value=os.path.exists(STARTUP_LNK))
        self.row_vars = {k: tk.BooleanVar(value=self.cfg["rows"][k]) for k in ROW_ORDER}
        self.menu = self._build_menu()
        self._apply_rows(first=True)
        for w in (r, *self.rows.values(), self.warn):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<MouseWheel>", self._wheel)
            w.bind("<Button-3>", self._popup)

        r.update_idletasks()
        self._place()
        psutil.cpu_percent(interval=None)  # prime the counter

        if not self.visible:
            r.withdraw()
        self._fps_sync()

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

    def _apply_rows(self, first=False):
        for lbl in self.rows.values():
            lbl.pack_forget()
        for name in ROW_ORDER:
            if self.cfg["rows"][name]:
                self.rows[name].pack(fill="x", before=self.warn if self.warn.winfo_ismapped() else None)
        self._net_prev = None
        if self.cfg["rows"]["CPU"]:
            psutil.cpu_percent(interval=None)  # re-prime so the next reading is real
        if not first:
            self.root.update_idletasks()
            r = self.root
            x = max(0, min(r.winfo_x(), r.winfo_screenwidth() - r.winfo_reqwidth()))
            y = max(0, min(r.winfo_y(), r.winfo_screenheight() - r.winfo_reqheight()))
            r.geometry(f"+{x}+{y}")
            self._fps_sync()
            if self.visible:
                self._sample()

    def _fps_sync(self):
        """PresentMon runs only while the FPS row is on and the overlay is visible."""
        if self.visible and self.cfg["rows"]["FPS"]:
            self.fps.start()
        else:
            self.fps.stop()

    def _row_toggled(self, key):
        want = self.row_vars[key].get()
        if not want and sum(self.cfg["rows"].values()) <= 1:
            self.row_vars[key].set(True)  # never leave the overlay empty
            return
        self.cfg["rows"][key] = want
        self._apply_rows()
        save_config(self.cfg)

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
        show = tk.Menu(m, tearoff=0)
        for k in ROW_ORDER:
            show.add_checkbutton(label=ROW_LABELS[k], variable=self.row_vars[k],
                                 command=lambda k=k: self._row_toggled(k))
        m.add_cascade(label="Show", menu=show)
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
            self._fps_sync()
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.visible = True
            psutil.cpu_percent(interval=None)
            self._net_prev = None
            self._fps_sync()
            self._tick()
        self.cfg["visible"] = self.visible
        save_config(self.cfg)

    def quit(self):
        self.fps.stop()
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
    def _gpu_read(self, fn):
        if _GPU is None:
            return None
        try:
            return fn()
        except Exception:
            return None

    def _sample(self):
        on = self.cfg["rows"]  # hidden rows are never sampled
        vals = {}
        if on["CPU"]:
            vals["CPU"] = psutil.cpu_percent(interval=None)
        if on["RAM"]:
            vals["RAM"] = psutil.virtual_memory().percent
        if on["GPU"]:
            vals["GPU"] = self._gpu_read(lambda: pynvml.nvmlDeviceGetUtilizationRates(_GPU).gpu)
        if on["VRAM"]:
            def vram():
                mi = pynvml.nvmlDeviceGetMemoryInfo(_GPU)
                return mi.used * 100.0 / mi.total
            vals["VRAM"] = self._gpu_read(vram)
        if on["TEMP"]:
            c = self._gpu_read(lambda: pynvml.nvmlDeviceGetTemperature(_GPU, 0))
            vals["TEMP"] = None if c is None else c * 9 / 5 + 32

        for name, val in vals.items():
            if val is None:
                txt, col = f"{name:<4} n/a", color_for(None)
            elif name == "TEMP":
                txt, col = f"{name:<4} {val:3.0f}°F", color_for(val, 140, 167)
            else:
                txt, col = f"{name:<4} {val:3.0f}%", color_for(val)
            self.rows[name].config(text=txt, fg=col)

        if on["NET"]:
            n, now = psutil.net_io_counters(), time.monotonic()
            if self._net_prev is None:
                txt = "NET  ↓--   ↑--"
            else:
                dt = max(now - self._net_prev[0], 0.001)
                txt = (f"NET  ↓{fmt_speed((n.bytes_recv - self._net_prev[1]) / dt)}"
                       f" ↑{fmt_speed((n.bytes_sent - self._net_prev[2]) / dt)}")
            self._net_prev = (now, n.bytes_recv, n.bytes_sent)
            self.rows["NET"].config(text=txt, fg=NET_COLOR)

        if on["FPS"]:
            if not self.fps.available():
                self.rows["FPS"].config(text="FPS  see README", fg=color_for(None))
            else:
                fps = self.fps.fps_for(foreground_pid())
                self.rows["FPS"].config(text=f"FPS  {fps:3d}" if fps else "FPS   --", fg=fps_color(fps))

    def _tick(self):
        if not self.visible:
            return
        self._sample()
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
