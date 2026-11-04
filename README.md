# LCS-Resources

A tiny always-on-top overlay for Windows that shows **CPU %, GPU %, and RAM %** in a small borderless box. Built by LionClad Studios.

- **Drag** it anywhere; the position is remembered.
- **Mouse wheel** over it changes opacity (15% to 100%).
- **Ctrl+Shift+M** shows or hides it from anywhere (global hotkey).
- **Right-click** for opacity presets, reset position, "Start with Windows", hide, and quit.
- Numbers turn green under 50%, yellow at 50-79%, red at 80%+.

## Install

Requires Windows and Python 3.10+. GPU usage needs an NVIDIA card (on anything else the GPU row shows `n/a`).

```
pip install -r requirements.txt
pythonw lcs_resources.py
```

`pythonw` runs it with no console window. To launch it at login, right-click the overlay and tick **Start with Windows**.

## Cost

Measured on Python 3.14 with an RTX 4070 Ti SUPER, updating once per second:

- CPU: about 0.01-0.02% of the whole machine
- RAM: about 55 MB working set (about 39 MB private) - that's the Python + tkinter floor
- While hidden, sampling stops entirely.

## Settings

`config.json` (created next to the script) holds `x`, `y`, `opacity`, `visible`, and `refresh_ms`. Delete it to reset. Errors, if any, go to `lcs_resources.log`.

If another app already owns Ctrl+Shift+M, the overlay shows "hotkey in use".

## License

MIT
