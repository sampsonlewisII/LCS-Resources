# LCS-Resources

A tiny always-on-top overlay for Windows that shows **CPU %, GPU %, VRAM %, GPU temperature, RAM %, and network speed** in a small borderless box. Built by LionClad Studios.

- **Drag** it anywhere; the position is remembered.
- **Mouse wheel** over it changes opacity (15% to 100%).
- **Ctrl+Shift+M** shows or hides it from anywhere (global hotkey).
- **Right-click** for opacity presets, a **Show** submenu to switch any row on or off (the box resizes to fit; the last row can't be turned off), reset position, "Start with Windows", hide, and quit.
- Percentages turn green under 50%, yellow at 50-79%, red at 80%+. GPU temperature is in °F (green under 140, yellow to 166, red from 167). Network shows download ↓ and upload ↑ in KB/s or MB/s.

## Install

Requires Windows and Python 3.10+. The GPU, VRAM and temperature rows need an NVIDIA card (on anything else they show `n/a`).

```
pip install -r requirements.txt
pythonw lcs_resources.py
```

`pythonw` runs it with no console window. To launch it at login, right-click the overlay and tick **Start with Windows**.

## Cost

Measured on Python 3.14 with an RTX 4070 Ti SUPER, updating once per second:

- CPU: about 0.015% of the whole machine with all six rows on
- RAM: about 57 MB working set (about 39 MB private) - that's the Python + tkinter floor
- A row you switch off is never sampled, and while the whole overlay is hidden, sampling stops entirely.

## Settings

`config.json` (created next to the script) holds `x`, `y`, `opacity`, `visible`, `refresh_ms`, and `rows` (which rows are shown). Delete it to reset. Errors, if any, go to `lcs_resources.log`.

If another app already owns Ctrl+Shift+M, the overlay shows "hotkey in use".

## License

MIT
