# LCS-Resources

A tiny always-on-top overlay for Windows that shows **CPU %, GPU %, VRAM %, GPU temperature, RAM %, network speed, and FPS** in a small borderless box. Built by LionClad Studios.

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

### FPS row (optional setup)

FPS is read with Intel's open-source [PresentMon](https://github.com/GameTechDev/PresentMon) (MIT, signed by Intel). The overlay doesn't hook or inject into any game; it only reads Windows' own "frame presented" events, the same way Xbox Game Bar does. Without PresentMon the FPS row shows `see README` and everything else works normally.

1. Download PresentMon into a `bin` folder next to the script (PowerShell, run from this folder):

   ```
   New-Item -ItemType Directory -Force bin | Out-Null
   Invoke-WebRequest https://github.com/GameTechDev/PresentMon/releases/download/v2.6.0/PresentMon-2.6.0-x64.exe -OutFile bin\PresentMon.exe
   (Get-FileHash bin\PresentMon.exe).Hash
   ```

   The hash for v2.6.0 should be `B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF`. (Or set `presentmon_path` in `config.json` to a copy you already have.)

2. Allow your account to read those events. Either add yourself to the built-in **Performance Log Users** group once, from an **administrator** prompt, then sign out and back in:

   ```
   net localgroup "Performance Log Users" %USERNAME% /add
   ```

   or just run the overlay as administrator.

How it behaves: it shows the FPS of whatever window is in front (it also checks that app's child processes, which covers browsers and launchers), and `FPS --` when nothing in front is drawing frames. It is the 1-second average, shaded red under 30, yellow 30-59, green 60+. The PresentMon helper runs only while the FPS row is on and the overlay is visible, and Windows kills it automatically if the overlay is ever force-closed.

## Cost

Measured on Python 3.14 with an RTX 4070 Ti SUPER, updating once per second:

- CPU: about 0.015% of the whole machine with the six system rows on; about 0.03% with FPS on too (plus about 0.006% for the PresentMon helper)
- RAM: about 57-60 MB working set (about 40 MB private) - that's the Python + tkinter floor - plus about 15 MB for PresentMon when FPS is on
- A row you switch off is never sampled, and while the whole overlay is hidden, sampling (and PresentMon) stops entirely.

## Settings

`config.json` (created next to the script) holds `x`, `y`, `opacity`, `visible`, `refresh_ms`, `presentmon_path` (optional), and `rows` (which rows are shown). Delete it to reset. Errors, if any, go to `lcs_resources.log`.

If another app already owns Ctrl+Shift+M, the overlay shows "hotkey in use".

## License

MIT
