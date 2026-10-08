"""HUD-карточки Джарвиса в стиле фильма (CustomTkinter)."""
from __future__ import annotations

import time

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover
    ctk = None

import tkinter as tk

FONT = "Segoe UI"

HUD_THEMES: dict[str, dict] = {
    "jarvis_blue": {
        "label": "Джарвис синий (как в фильме)",
        "accent": "#17c3e8", "glow": "#0a4a5e", "bg": "#0b141c",
        "fg": "#e8f6fb", "sub": "#7fb6c9", "ok": "#3ecf8e", "err": "#ff6b6b",
    },
    "arc_reactor": {
        "label": "Реактор — бело-голубой",
        "accent": "#bff1ff", "glow": "#1c5a72", "bg": "#0a1118",
        "fg": "#ffffff", "sub": "#9fd8ea", "ok": "#3ecf8e", "err": "#ff6b6b",
    },
    "iron_red": {
        "label": "Железный красный",
        "accent": "#ff4d4d", "glow": "#5e1414", "bg": "#1a0e0e",
        "fg": "#ffecec", "sub": "#d99a9a", "ok": "#3ecf8e", "err": "#ffb3b3",
    },
    "hulk_green": {
        "label": "Халк — зелёный",
        "accent": "#3eff8e", "glow": "#0e4a2a", "bg": "#0b1710",
        "fg": "#eafff2", "sub": "#8fd6a8", "ok": "#3eff8e", "err": "#ff6b6b",
    },
    "vibranium": {
        "label": "Вибраниум — фиолет",
        "accent": "#b06bff", "glow": "#3a1c5e", "bg": "#130e1c",
        "fg": "#f3eaff", "sub": "#b99fe0", "ok": "#3ecf8e", "err": "#ff6b6b",
    },
    "gold": {
        "label": "Золото Старка",
        "accent": "#ffc93e", "glow": "#5e4410", "bg": "#191307",
        "fg": "#fff6e0", "sub": "#d6bd7f", "ok": "#3ecf8e", "err": "#ff6b6b",
    },
}

DEFAULT_THEME = "jarvis_blue"


def get_theme(name: str | None) -> dict:
    return HUD_THEMES.get(str(name or ""), HUD_THEMES[DEFAULT_THEME])


def theme_names() -> list[str]:
    return list(HUD_THEMES)


def theme_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in HUD_THEMES.items()}


_FALLBACK_STACK: list = []


def _fallback_card(root, message: str, ok: bool, duration_ms: int) -> None:
    bg = "#1f3d2b" if ok else "#3d1f1f"
    w = tk.Toplevel(root)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.configure(bg=bg)
    tk.Label(w, text=message, bg=bg, fg="#ffffff", font=(FONT, 11),
             padx=16, pady=10, wraplength=320, justify="left").pack()
    _FALLBACK_STACK.append(w)
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        y = sh - 60
        for win in reversed(_FALLBACK_STACK[-5:]):
            try:
                win.update_idletasks()
                y -= win.winfo_reqheight()
                win.geometry(f"+{sw - win.winfo_reqwidth() - 20}+{y}")
                y -= 8
            except Exception:
                pass
    except Exception:
        pass

    def _rm(w=w):
        try:
            if w in _FALLBACK_STACK:
                _FALLBACK_STACK.remove(w)
            w.destroy()
        except Exception:
            pass
    w.after(max(800, duration_ms), _rm)
def show_card(root, message, ok=True, duration_ms=3000,
              hud_cfg=None, stack=None, layout_cb=None):
    hud_cfg = dict(hud_cfg or {})
    if ctk is None:
        _fallback_card(root, message, ok, duration_ms)
        return None
    theme = get_theme(hud_cfg.get("theme"))
    try:
        width = int(hud_cfg.get("width", 360))
    except (TypeError, ValueError):
        width = 360
    width = max(260, min(520, width))
    glow_on = bool(hud_cfg.get("glow", True))
    anim_on = bool(hud_cfg.get("anim", True))
    duration_ms = max(900, int(duration_ms or 3000))
    accent = theme["accent"]
    status_color = theme["ok"] if ok else theme["err"]
    try:
        w = ctk.CTkToplevel(root)
    except Exception:
        _fallback_card(root, message, ok, duration_ms)
        return None
    try:
        w.overrideredirect(True)
        w.attributes("-topmost", True)
    except Exception:
        pass
    glow_color = theme["glow"] if glow_on else theme["bg"]
    try:
        outer = ctk.CTkFrame(w, fg_color=glow_color, corner_radius=18)
        outer.pack(padx=2, pady=2)
        card = ctk.CTkFrame(outer, fg_color=theme["bg"], corner_radius=14,
                            border_color=accent, border_width=2)
        card.pack(padx=3, pady=3)
    except Exception:
        _fallback_card(root, message, ok, duration_ms)
        try:
            w.destroy()
        except Exception:
            pass
        return None
    try:
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 2))
        dot = ctk.CTkLabel(head, text="●",
                           font=ctk.CTkFont(family=FONT, size=13,
                                            weight="bold"),
                           text_color=status_color, width=18)
        dot.pack(side="left")
        title = ctk.CTkLabel(head, text="J.A.R.V.I.S.",
                             font=ctk.CTkFont(family=FONT, size=12,
                                              weight="bold"),
                             text_color=accent)
        title.pack(side="left", padx=(2, 0))
        clock = ctk.CTkLabel(head, text=time.strftime("%H:%M:%S"),
                             font=ctk.CTkFont(family=FONT, size=11),
                             text_color=theme["sub"])
        clock.pack(side="right")
        sep = ctk.CTkFrame(card, fg_color=accent, height=1)
        sep.pack(fill="x", padx=14, pady=(4, 2))
    except Exception:
        pass
    try:
        body = ctk.CTkLabel(card, text=message,
                            font=ctk.CTkFont(family=FONT, size=12),
                            text_color=theme["fg"], wraplength=width - 48,
                            justify="left", anchor="w")
        body.pack(fill="x", padx=14, pady=(4, 8))
    except Exception:
        pass
    bar = None
    try:
        bar = ctk.CTkProgressBar(card, height=3, corner_radius=2,
                                 fg_color=theme["glow"],
                                 progress_color=accent, border_width=0)
        bar.pack(fill="x", padx=14, pady=(0, 10))
        bar.set(1.0)
    except Exception:
        bar = None
    if stack is not None:
        stack.append(w)
    if layout_cb is not None:
        try:
            layout_cb()
        except Exception:
            pass
    state = {"dead": False}

    def destroy():
        if state["dead"]:
            return
        state["dead"] = True
        try:
            if stack is not None and w in stack:
                stack.remove(w)
        except Exception:
            pass
        try:
            w.destroy()
        except Exception:
            pass
        if layout_cb is not None:
            try:
                layout_cb()
            except Exception:
                pass
    try:
        if anim_on:
            try:
                w.attributes("-alpha", 0.0)
            except Exception:
                pass
            si, di = 8, 18
            so, do = 8, 30

            def fade_in(i=0):
                if state["dead"]:
                    return
                try:
                    w.attributes("-alpha", min(1.0, (i + 1) / si))
                except Exception:
                    pass
                if i + 1 < si:
                    w.after(di, lambda: fade_in(i + 1))

            def fade_out(i=0):
                if state["dead"]:
                    return
                if i >= so:
                    destroy()
                    return
                try:
                    w.attributes("-alpha", max(0.0, 1.0 - (i + 1) / so))
                except Exception:
                    pass
                w.after(do, lambda: fade_out(i + 1))
            total = max(1, duration_ms - si * di - so * do - 120)
            born = time.monotonic()

            def tick():
                if state["dead"]:
                    return
                el = (time.monotonic() - born) * 1000
                try:
                    if bar is not None:
                        bar.set(max(0.0, 1.0 - el / total))
                except Exception:
                    pass
                if el >= total:
                    fade_out()
                else:
                    w.after(80, tick)
            w.after(30, lambda: (fade_in(), w.after(si * di + 40, tick)))
        else:
            if bar is not None:
                try:
                    bar.set(0.0)
                except Exception:
                    pass
            w.after(duration_ms, destroy)
    except Exception:
        try:
            w.after(duration_ms, destroy)
        except Exception:
            pass
    return w


def preview(parent, hud_cfg=None, message="Systems nominal"):
    show_card(parent, message, True, 3500, hud_cfg or {}, None, None)

