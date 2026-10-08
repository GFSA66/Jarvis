"""Окно настроек Джарвиса (customtkinter).

Открывается голосовой командой «открой настройки». Работает в Tk-потоке Джарвиса
(как дочернее окно его скрытого корня), поэтому отдельного mainloop не создаёт.
Само окно ничего не пишет на диск: по «Сохранить» оно собирает словарь-патч
и отдаёт его в on_save(patch) — сохранением и применением занимается jarvis.py.

Автозапуск через Планировщик заданий тоже делает jarvis.py: сюда передаётся объект
autostart с методами status(), apply(enabled, admin) и target_text().
Вкладка «Нейросеть» получает модуль jarvis_ai (PRESETS, test_connection), а кнопка
«Проверить голос» — функцию say(текст).
"""
from __future__ import annotations

import re
import sys
import threading
import webbrowser
import hashlib
import secrets
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

URL_LABELS = [
    ("films", "Фильмы", "«фильм», «кино»"),
    ("anime", "Аниме", "«аниме»"),
    ("github", "GitHub", "«гитхаб»"),
    ("parts", "Комплектующие", "«комплектующие»"),
    ("classroom", "Google Classroom", "«пара», «урок»"),
    ("logika", "Logika backoffice", "«логика»"),
    ("roblox", "Roblox", "«роблокс»"),
]
PATH_LABELS = [
    ("chrome", "Chrome", "chrome.exe"),
    ("steam", "Steam", "steam.exe"),
    ("discord", "Discord", "Discord.exe или Update.exe"),
    ("telegram", "Telegram", "Telegram.exe"),
    ("genshin", "Genshin Impact", "GenshinImpact.exe"),
    ("minecraft", "Minecraft Launcher", "MinecraftLauncher.exe"),
    ("prism", "Prism Launcher", "prismlauncher.exe"),
]
PHRASE_LABELS = [
    ("pause", "Пауза"),
    ("resume", "Продолжить после паузы"),
    ("study_mode", "Учебный режим"),
    ("play_mode", "Игровой режим"),
]
AI_STYLES = [("film", "Как в кино — учтивый, с характером"),
             ("dry", "Сухо — только факты"),
             ("brief", "Кратко — одно-два предложения")]

# --- оформление (JARVIS HUD) ------------------------------------------------
FONT = "Segoe UI"
WINDOW_BG, HEADER_BG = "#07111f", "#0b1d30"
ACCENT, ACCENT_H = "#00d4ff", "#00a8cc"
DANGER, DANGER_H = "#c94a4a", "#a33a3a"
OK_COLOR, ERR_COLOR, MUTED = "#3ecf8e", "#ff6b6b", "#8b97a6"
CARD, ROW_A, ROW_B = "#101d2e", "#0b1625", "#14253a"
CARD_BORDER = "#234965"
TITLE_COLOR = "#00d4ff"
GHOST_H = "#2b3646"

ICON = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "jarvis.ico"

_instance = None
_hotkeys_fixed = False


def _norm(s: str) -> str:
    return s.strip().lower().replace("ё", "е")


def _font(size: int = 13, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def _set_icon(win) -> None:
    """CTk сам ставит свою иконку через 200 мс — перебиваем её чуть позже."""
    def apply():
        try:
            if win.winfo_exists() and ICON.is_file():
                win.iconbitmap(str(ICON))
        except Exception:
            pass
    win.after(300, apply)


def _fix_ru_hotkeys(win) -> None:
    """Ctrl+C/V/X не работают в Tk при русской раскладке — чиним для всех полей ввода."""
    global _hotkeys_fixed
    if _hotkeys_fixed:
        return
    _hotkeys_fixed = True
    events = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>"}  # коды клавиш V, C, X

    def handler(e):
        ev = events.get(e.keycode)
        if ev:
            e.widget.event_generate(ev)
            return "break"

    win.bind_class("Entry", "<Control-KeyPress>", handler)


def _place_over(win, parent) -> None:
    """Центрируем окно над родителем (размеры берём в реальных пикселях — без путаницы с масштабом)."""
    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_reqheight()) // 2
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def _make_modal(d, parent) -> None:
    d.transient(parent)

    def grab():
        try:
            if d.winfo_exists():
                d.grab_set()
                d.focus_force()
        except tk.TclError:
            pass
    d.after(200, grab)  # у CTkToplevel окно появляется не сразу — раньше grab_set падает


def _entry(parent, value: str = "", width: int = 300, placeholder: str = "") -> ctk.CTkEntry:
    kw = {"placeholder_text": placeholder} if placeholder else {}
    e = ctk.CTkEntry(parent, width=width, height=32, font=_font(), **kw)
    if value:
        e.insert(0, value)
    return e


def _button(parent, text, command, kind="normal", width=110) -> ctk.CTkButton:
    colors = {
        "normal": dict(fg_color=GHOST_H, hover_color="#38465a"),
        "accent": dict(fg_color=ACCENT, hover_color=ACCENT_H, text_color="#04141a"),
        "danger": dict(fg_color=DANGER, hover_color=DANGER_H),
    }[kind]
    return ctk.CTkButton(parent, text=text, command=command, width=width, height=32,
                         font=_font(13, kind == "accent"), corner_radius=8, **colors)


# ============================================================================
#  Диалоги
# ============================================================================

def ask(parent, title: str, text: str, on_yes=None, yes: str = "OK", no: str = "Отмена",
        danger: bool = False) -> None:
    """Сообщение (on_yes=None — одна кнопка) или вопрос да/нет."""
    d = ctk.CTkToplevel(parent)
    d.title(title)
    d.resizable(False, False)
    _set_icon(d)
    ctk.CTkLabel(d, text=text, font=_font(), wraplength=360, justify="left").pack(
        padx=22, pady=(20, 14), anchor="w")
    bar = ctk.CTkFrame(d, fg_color="transparent")
    bar.pack(fill="x", padx=22, pady=(0, 18))

    def confirm(_e=None):
        d.destroy()
        if on_yes:
            on_yes()

    _button(bar, yes, confirm, "danger" if danger else "accent", 100).pack(side="right")
    if on_yes:
        _button(bar, no, d.destroy, width=100).pack(side="right", padx=(0, 8))
    d.bind("<Escape>", lambda e: d.destroy())
    d.bind("<Return>", confirm)
    _place_over(d, parent)
    _make_modal(d, parent)


class EntryDialog:
    """Окно «Добавить / Изменить запись» с несколькими полями."""

    def __init__(self, parent, title, columns, initial, browse_col, validate, on_ok):
        self.validate, self.on_ok, self.initial = validate, on_ok, initial
        d = self.d = ctk.CTkToplevel(parent)
        d.title(title)
        d.resizable(False, False)
        _set_icon(d)

        body = ctk.CTkFrame(d, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(18, 4))
        body.grid_columnconfigure(0, weight=1)
        self.entries = []
        r = 0
        for i, (name, *_rest) in enumerate(columns):
            ctk.CTkLabel(body, text=name, font=_font(12), text_color=MUTED).grid(
                row=r, column=0, sticky="w", pady=(0 if i == 0 else 10, 3))
            e = _entry(body, initial[i] if initial else "", width=440)
            e.grid(row=r + 1, column=0, sticky="ew")
            if i == browse_col:
                _button(body, "Обзор…", lambda e=e: self._browse(e), width=90).grid(
                    row=r + 1, column=1, padx=(8, 0))
            self.entries.append(e)
            r += 2
        self.err = ctk.CTkLabel(body, text="", font=_font(12), text_color=ERR_COLOR,
                                wraplength=440, justify="left")
        self.err.grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

        bar = ctk.CTkFrame(d, fg_color="transparent")
        bar.pack(fill="x", padx=22, pady=(6, 18))
        _button(bar, "Сохранить", self.ok, "accent").pack(side="right")
        _button(bar, "Отмена", d.destroy).pack(side="right", padx=(0, 8))
        d.bind("<Return>", self.ok)
        d.bind("<Escape>", lambda e: d.destroy())
        _place_over(d, parent)
        _make_modal(d, parent)
        d.after(250, self.entries[0].focus_set)

    def _browse(self, entry) -> None:
        path = filedialog.askopenfilename(parent=self.d, title="Выбери программу или файл")
        if path:
            entry.delete(0, "end")
            entry.insert(0, path.replace("/", "\\"))

    def ok(self, _e=None) -> None:
        vals = [e.get().strip() for e in self.entries]
        msg = self.validate(vals, self.initial)
        if msg:
            self.err.configure(text=msg)
            return
        vals[0] = _norm(vals[0])
        self.d.destroy()
        self.on_ok(vals)


# ============================================================================
#  Таблица «фраза → значение»
# ============================================================================

class TableTab(ctk.CTkFrame):
    """Список записей с поиском и кнопками ✎ / ✕ у каждой строки.

    columns: [(заголовок, минимальная ширина, вес растяжения, лимит символов), ...]
    """

    ACTIONS_W = 78

    def __init__(self, parent, win, hint, columns, browse_col=None, validators=None):
        super().__init__(parent, fg_color="transparent")
        self.win, self.columns = win, columns
        self.browse_col, self.validators = browse_col, validators or {}
        self.data: list[list[str]] = []
        self._after = None

        self.hint = ctk.CTkLabel(self, text=hint, font=_font(12), text_color=MUTED,
                                 justify="left", anchor="w", wraplength=700)
        self.hint.pack(fill="x", pady=(0, 8))
        self.bind("<Configure>", lambda e: self.hint.configure(wraplength=max(300, e.width - 24)))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        self.search = ctk.CTkEntry(bar, height=32, font=_font(), placeholder_text="🔍  Поиск…")
        self.search.pack(side="left", fill="x", expand=True)
        self.search.bind("<KeyRelease>", lambda e: self._schedule())
        _button(bar, "＋  Добавить", self.add, "accent", 120).pack(side="left", padx=(8, 0))

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=(10, 0))
        self._grid_cols(head, extra=self.ACTIONS_W + 22)  # + место под полосу прокрутки
        for i, (title, *_r) in enumerate(columns):
            ctk.CTkLabel(head, text=title.upper(), font=_font(11, True), text_color=MUTED,
                         anchor="w", width=10).grid(row=0, column=i, sticky="ew", padx=(8, 0))

        self.body = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=10)
        self.body.pack(fill="both", expand=True, pady=(4, 0))
        self.counter = ctk.CTkLabel(self, text="", font=_font(11), text_color=MUTED, anchor="e")
        self.counter.pack(fill="x", pady=(4, 0))

    def _grid_cols(self, frame, extra=0) -> None:
        for i, (_t, minw, weight, _lim) in enumerate(self.columns):
            frame.grid_columnconfigure(i, minsize=minw, weight=weight)
        frame.grid_columnconfigure(len(self.columns), minsize=extra)

    # --- данные -----------------------------------------------------------
    def load(self, rows) -> None:
        self.data = [[str(x) for x in r] for r in rows]
        self._render()

    def rows(self) -> list[tuple]:
        return [tuple(r) for r in self.data]

    def _schedule(self) -> None:
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(150, self._render)

    def _render(self) -> None:
        self._after = None
        for w in self.body.winfo_children():
            w.destroy()
        q = _norm(self.search.get())
        shown = [i for i, r in enumerate(self.data) if not q or any(q in _norm(c) for c in r)]
        for n, i in enumerate(shown):
            self._row(i, n)
        if not shown:
            ctk.CTkLabel(self.body, font=_font(), text_color=MUTED,
                         text="Ничего не найдено." if self.data else "Пока пусто — нажми «Добавить».").pack(pady=30)
        total = len(self.data)
        self.counter.configure(text=f"Записей: {total}" + (f"  ·  показано: {len(shown)}" if q else ""))

    def _row(self, i: int, n: int) -> None:
        row = ctk.CTkFrame(self.body, fg_color=ROW_A if n % 2 == 0 else ROW_B, corner_radius=6, height=36)
        row.pack(fill="x", pady=1)
        self._grid_cols(row)
        row.grid_columnconfigure(len(self.columns), minsize=self.ACTIONS_W)
        for c, text in enumerate(self.data[i]):
            # ячейка фиксированной высоты и без «распирания»: длинный текст обрезается, а не двигает колонки
            cell = ctk.CTkFrame(row, fg_color="transparent", width=10, height=30)
            cell.grid(row=0, column=c, sticky="ew", padx=(8, 0), pady=3)
            lab = ctk.CTkLabel(cell, text=_short(text, self.columns[c][3]), font=_font(), anchor="w")
            lab.place(x=0, rely=0.5, anchor="w")
            for wdg in (cell, lab):
                wdg.bind("<Double-Button-1>", lambda e, i=i: self.edit(i))
        acts = ctk.CTkFrame(row, fg_color="transparent")
        acts.grid(row=0, column=len(self.columns), padx=(0, 4))
        for glyph, cmd, hover in (("✎", lambda i=i: self.edit(i), GHOST_H),
                                  ("✕", lambda i=i: self.delete(i), DANGER)):
            ctk.CTkButton(acts, text=glyph, width=32, height=28, corner_radius=6, font=_font(14),
                          fg_color="transparent", hover_color=hover, command=cmd).pack(side="left", padx=1)
        row.bind("<Double-Button-1>", lambda e, i=i: self.edit(i))

    # --- кнопки -----------------------------------------------------------
    def add(self) -> None:
        def done(vals):
            self.data.append(vals)
            self.search.delete(0, "end")
            self._render()
        self._dialog("Новая запись", None, done)

    def edit(self, i: int) -> None:
        def done(vals):
            self.data[i] = vals
            self._render()
        self._dialog("Изменить запись", list(self.data[i]), done)

    def delete(self, i: int) -> None:
        def done():
            del self.data[i]
            self._render()
        ask(self.win, "Удалить запись", f"Удалить «{_short(self.data[i][0], 40)}»?",
            on_yes=done, yes="Удалить", danger=True)

    # --- проверка ----------------------------------------------------------
    def _validate(self, vals, initial):
        if any(not v for v in vals):
            return "Заполни все поля."
        for i, check in self.validators.items():
            msg = check(vals[i])
            if msg:
                return msg
        mine = _norm(initial[0]) if initial else None
        if _norm(vals[0]) in {_norm(r[0]) for r in self.data} and _norm(vals[0]) != mine:
            return "Такая фраза уже есть."
        return None

    def _dialog(self, title, initial, on_ok) -> None:
        EntryDialog(self.win, title, self.columns, initial, self.browse_col, self._validate, on_ok)


def _short(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ============================================================================
#  Главное окно
# ============================================================================

def open_settings(root, cfg: dict, on_save, autostart=None, ai=None, say=None,
                  history_read=None, history_clear=None, history_run=None) -> None:
    """Открыть окно (или поднять уже открытое). Вызывать из Tk-потока."""
    global _instance
    if _instance is not None:
        try:
            if _instance.win.winfo_exists():
                _instance.win.deiconify()
                _instance.win.lift()
                _instance.win.focus_force()
                return
        except tk.TclError:
            pass
    ctk.set_appearance_mode("dark")
    _fix_ru_hotkeys(root)
    _instance = SettingsWindow(root, cfg, on_save, autostart, ai, say,
                               history_read, history_clear, history_run)


class SettingsWindow:
    def __init__(self, root, cfg: dict, on_save, autostart=None, ai=None, say=None,
                 history_read=None, history_clear=None, history_run=None):
        self.cfg, self.on_save, self.autostart = cfg, on_save, autostart
        self.ai, self.say = ai, say
        self.history_read, self.history_clear, self.history_run = history_read, history_clear, history_run
        w = self.win = ctk.CTkToplevel(root)
        w.title("Джарвис — настройки")
        w.geometry("980x730")
        w.minsize(840, 610)
        w.configure(fg_color=WINDOW_BG)
        _set_icon(w)

        head = ctk.CTkFrame(w, fg_color=HEADER_BG, corner_radius=18,
                            border_width=1, border_color=CARD_BORDER)
        head.pack(fill="x", padx=18, pady=(18, 10))
        mark = ctk.CTkLabel(head, text="J", width=42, height=42, corner_radius=21,
                            fg_color=ACCENT, text_color="#04141a", font=_font(20, True))
        mark.pack(side="left", padx=(18, 12), pady=14)
        title_box = ctk.CTkFrame(head, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True, pady=12)
        ctk.CTkLabel(title_box, text="Центр управления Джарвисом", font=_font(22, True),
                     text_color="#f0f8ff").pack(anchor="w")
        ctk.CTkLabel(title_box, text="Изменения применяются после сохранения • Ctrl+S — сохранить",
                     font=_font(12), text_color=MUTED).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(head, text="●  ГОТОВ", font=_font(12, True), text_color=OK_COLOR,
                     fg_color="#102b29", corner_radius=12, padx=13, pady=7).pack(
                         side="right", padx=18, pady=14)

        tabs = self.tabs = ctk.CTkTabview(
            w, fg_color="#091522", corner_radius=16, border_width=1, border_color=CARD_BORDER,
            segmented_button_fg_color="#12253a", segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_H,
            segmented_button_unselected_color="#12253a",
            segmented_button_unselected_hover_color=GHOST_H)
        tabs._segmented_button.configure(font=_font(13, True))
        tabs.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        names = ["Мои команды", "Игры Steam", "Сайты", "Ссылки", "Общие",
                 "Безопасность", "Уведомления", "Интеграции", "Диктовка", "История"]
        if ai is not None:
            names.append("Нейросеть")
        t = {name: tabs.add(name) for name in names + ["Пути"]}

        self.t_cmd = TableTab(
            t["Мои команды"], w,
            "Скажи фразу — Джарвис откроет ссылку или запустит программу. Справа: ссылка (https://…), "
            "путь к .exe или папке (кнопка «Обзор») либо имя программы, например notepad.exe. "
            "Фраза ищется как начало слова: «блокнот» сработает на «открой блокнот».",
            [("Фраза", 200, 2, 40), ("Ссылка или программа", 300, 5, 120)], browse_col=1)
        self.t_games = TableTab(
            t["Игры Steam"], w,
            "Фраза и Steam appid (число из адреса store.steampowered.com/app/<appid>/…). "
            "Одну игру можно назвать по-разному — добавь несколько фраз.",
            [("Фраза", 220, 3, 40), ("Steam appid", 160, 2, 12)],
            validators={1: lambda v: None if v.isdigit() else "Steam appid — это число."})
        self.t_sites = TableTab(
            t["Сайты"], w,
            "Сайты для команды «открой …»: например, фраза «ютуб» → «открой ютуб».",
            [("Фраза", 200, 2, 40), ("Ссылка", 300, 5, 120)],
            validators={1: lambda v: None if re.match(r"https?://", v, re.I)
                        else "Ссылка должна начинаться с http:// или https://"})
        for tab in (self.t_cmd, self.t_games, self.t_sites):
            tab.pack(fill="both", expand=True, padx=4, pady=2)

        self._build_links(t["Ссылки"])
        self._build_general(t["Общие"])
        self._build_security(t["Безопасность"])
        self._build_notifications(t["Уведомления"])
        self._build_integrations(t["Интеграции"])
        self._build_dictation(t["Диктовка"])
        self._build_history(t["История"])
        if ai is not None:
            self._build_ai(t["Нейросеть"])
        self._build_paths(t["Пути"])

        self.t_cmd.load((c["phrase"], c["target"]) for c in cfg["commands"])
        self.t_games.load(sorted(cfg["games"].items()))
        self.t_sites.load(sorted(cfg["sites"].items()))

        bottom = ctk.CTkFrame(w, fg_color=HEADER_BG, corner_radius=14,
                              border_width=1, border_color=CARD_BORDER)
        bottom.pack(fill="x", padx=18, pady=(0, 18))
        self.status = ctk.CTkLabel(bottom, text="Готово к настройке", font=_font(13),
                                   text_color=MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=(16, 8), pady=10)
        _button(bottom, "Закрыть", w.destroy, width=100).pack(side="right")
        self.btn_save = _button(bottom, "Сохранить", self.save, "accent", 120)
        self.btn_save.pack(side="right", padx=(0, 10), pady=8)
        bottom.winfo_children()[-1].pack_configure(pady=8)
        w.bind("<Control-s>", lambda e: self.save())

        w.lift()
        w.focus_force()

    # --- вкладки ---------------------------------------------------------
    @staticmethod
    def _card(parent, title: str, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=CARD_BORDER)
        card.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 12))
        # 0 — подпись фиксированной ширины, 1 — поле, 2 — подсказка тянется
        card.grid_columnconfigure(0, minsize=250)
        card.grid_columnconfigure(1, weight=0)
        card.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(card, text=title, font=_font(14, True), text_color=TITLE_COLOR).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(14, 8))
        return card

    @staticmethod
    def _field(card, r: int, label: str, entry, note: str = "") -> None:
        ctk.CTkLabel(card, text=label, font=_font(), anchor="w").grid(
            row=r, column=0, sticky="w", padx=(18, 12), pady=6)
        try:
            entry.grid_configure(sticky="w")
        except Exception:
            pass
        entry.grid(row=r, column=1, sticky="w", padx=(0, 12), pady=6)
        if note:
            ctk.CTkLabel(card, text=note, font=_font(11), text_color=MUTED,
                         anchor="w", justify="left", wraplength=320).grid(
                row=r, column=2, sticky="w", padx=(0, 18), pady=6)

    def _build_links(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="Ссылки для встроенных команд. Пустое поле — команда отключена.",
                     font=_font(12), text_color=MUTED, anchor="w").grid(row=0, column=0, sticky="w", padx=4, pady=(0, 8))
        card = self._card(tab, "Ссылки", 1)
        self.v_urls = {}
        for i, (key, label, say) in enumerate(URL_LABELS, start=1):
            self.v_urls[key] = _entry(card, self.cfg["urls"].get(key) or "", placeholder="https://…")
            self._field(card, i, label, self.v_urls[key], say)
        ctk.CTkFrame(card, fg_color="transparent", height=8).grid(row=len(URL_LABELS) + 1, column=0)

    def _build_general(self, tab) -> None:
        c = self.cfg
        sf = self.general_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        sf.pack(fill="both", expand=True)
        sf.grid_columnconfigure(0, weight=1)

        # --- голос и выключение
        card = self._card(sf, "Голос и питание", 0)
        self.sw_voice = ctk.CTkSwitch(card, text="Голосовые ответы", font=_font(), progress_color=ACCENT)
        self.sw_voice.grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=5)
        if c["voice"]["enabled"]:
            self.sw_voice.select()
        if self.say is not None:
            _button(card, "🔊  Проверить голос",
                    lambda: self.say("Проверка голоса. Джарвис на связи. Это живой нейроголос."), width=150).grid(
                row=1, column=2, padx=(0, 16), pady=5)
        # движок + живой голос Piper
        voices = c.get("voice", {})
        eng = (voices.get("engine") or "piper").lower()
        cur_pv = (voices.get("piper_voice") or "dmitri").lower()
        self.v_engine = ctk.CTkOptionMenu(card, values=["piper (живой)", "sapi (системный)"],
                                          font=_font(), width=170)
        self.v_engine.set("piper (живой)" if eng == "piper" else "sapi (системный)")
        self._field(card, 2, "Движок голоса", self.v_engine, "piper — живой нейроголос офлайн")
        self.v_engine.grid_configure(sticky="w")
        self.v_piper = ctk.CTkOptionMenu(
            card, values=["dmitri — мужской, живой", "ruslan — мужской, спокойный",
                          "irina — женский", "denis — мужской"],
            font=_font(), width=250)
        labels = {"dmitri": "dmitri — мужской, живой", "ruslan": "ruslan — мужской, спокойный",
                  "irina": "irina — женский", "denis": "denis — мужской"}
        self.v_piper.set(labels.get(cur_pv, labels["dmitri"]))
        self._field(card, 3, "Живой голос", self.v_piper, "первая реплика скачает ~63 МБ, дальше офлайн")
        self.v_piper.grid_configure(sticky="w")
        self.v_delay = _entry(card, str(c["shutdown_delay_sec"]), width=80)
        self._field(card, 4, "Задержка выключения / перезагрузки", self.v_delay, "секунд, от 0 до 600")
        self.v_delay.grid_configure(sticky="w")
        ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=5, column=0)

        # --- диктовка («надиктуй …» в активное окно)
        card = self._card(sf, "Диктовка («надиктуй …»)", 1)
        dc = c.get("dictation", {}) or {}
        self.v_dict_delay = _entry(card, str(dc.get("delay_sec", 3)), width=80)
        self._field(card, 1, "Пауза перед вставкой", self.v_dict_delay,
                    "секунд на клик в нужное окно (0 — вставлять сразу)")
        self.v_dict_delay.grid_configure(sticky="w")
        self.v_dict_paste = _entry(card, str(dc.get("paste_delay", 0.6)), width=80)
        self._field(card, 2, "Пауза перед Ctrl+V", self.v_dict_paste,
                    "секунд; если вставляется часть текста — увеличь до 1–1.5")
        self.v_dict_paste.grid_configure(sticky="w")
        self.sw_dict_clip = ctk.CTkSwitch(card, text="Возвращать буфер обмена после вставки",
                                          font=_font(), progress_color=ACCENT)
        self.sw_dict_clip.grid(row=3, column=0, columnspan=3, sticky="w", padx=16, pady=5)
        if dc.get("restore_clipboard", True):
            self.sw_dict_clip.select()
        ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=4, column=0)

        # --- слово-активатор
        card = self._card(sf, "Слово-активатор", 2)
        self.sw_wake = ctk.CTkSwitch(card, text="Реагировать только на фразы со словом-активатором",
                                     font=_font(), progress_color=ACCENT)
        self.sw_wake.grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=5)
        if c["wake_word"]["enabled"]:
            self.sw_wake.select()
        self.v_wake = _entry(card, c["wake_word"]["word"], width=200)
        self._field(card, 2, "Слово", self.v_wake)
        self.v_wake.grid_configure(sticky="w")
        ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=3, column=0)

        # --- Chrome
        card = self._card(sf, "Chrome", 3)
        self.v_prof_main = _entry(card, c["chrome"]["main_profile"] or "Default", width=200)
        self.v_prof_study = _entry(card, c["chrome"]["study_profile"] or "", width=200, placeholder="как основной")
        self._field(card, 1, "Профиль основной", self.v_prof_main, "папка профиля: Default, Profile 1…")
        self._field(card, 2, "Профиль учебный", self.v_prof_study)
        self.v_prof_main.grid_configure(sticky="w")
        self.v_prof_study.grid_configure(sticky="w")
        ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=3, column=0)

        # --- планировщик
        card = self._card(sf, "Планировщик заданий Windows", 4)
        self.v_task = _entry(card, c["genshin_task"] or "", width=240, placeholder="имя задачи")
        self._field(card, 1, "Задача для запуска Genshin", self.v_task, "schtasks /run — если игре нужны права админа")
        self.v_task.grid_configure(sticky="w")
        r = 2
        self._auto0, self._auto_stale = (False, False), False
        if self.autostart is not None:
            st = self.autostart.status()
            self._auto0 = (bool(st), bool(st and st["admin"]))
            self._auto_stale = bool(st and not self.autostart.same_target(st["command"]))
            self.sw_auto = ctk.CTkSwitch(card, text="Запускать Джарвиса при входе в Windows",
                                         font=_font(), progress_color=ACCENT, command=self._auto_toggled)
            self.sw_auto.grid(row=r, column=0, columnspan=3, sticky="w", padx=16, pady=(10, 4))
            self.sw_admin = ctk.CTkSwitch(card, text="С правами администратора (без запроса UAC)",
                                          font=_font(), progress_color=ACCENT)
            self.sw_admin.grid(row=r + 1, column=0, columnspan=3, sticky="w", padx=(44, 16), pady=4)
            if st:
                self.sw_auto.select()
                if st["admin"]:
                    self.sw_admin.select()
            self.lbl_auto = ctk.CTkLabel(card, text="", font=_font(11), text_color=MUTED,
                                         justify="left", anchor="w", wraplength=640)
            self.lbl_auto.grid(row=r + 2, column=0, columnspan=3, sticky="w", padx=16, pady=(2, 12))
            self._auto_toggled()
            self._refresh_auto_label(st)
        else:
            ctk.CTkFrame(card, fg_color="transparent", height=6).grid(row=r, column=0)

        # --- фразы
        card = self._card(sf, "Фразы управления", 5)
        self.v_phr = {}
        for i, (key, label) in enumerate(PHRASE_LABELS, start=1):
            self.v_phr[key] = _entry(card, c["phrases"][key], width=320)
            self._field(card, i, label, self.v_phr[key])
            self.v_phr[key].grid_configure(sticky="w")
        ctk.CTkFrame(card, fg_color="transparent", height=6).grid(row=len(PHRASE_LABELS) + 1, column=0)

    def _build_ai(self, tab) -> None:
        a, presets = self.cfg["ai"], self.ai.PRESETS
        self._ai_labels = {k: v["label"] for k, v in presets.items()}
        self._ai_by_label = {v: k for k, v in self._ai_labels.items()}
        self._ai_prov = a["provider"] if a["provider"] in presets else "gemini"
        pre = presets[self._ai_prov]

        sf = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        sf.pack(fill="both", expand=True)
        sf.grid_columnconfigure(0, weight=1)
        card = self._card(sf, "Нейросеть: отвечает на вопросы голосом", 0)

        self.sw_ai = ctk.CTkSwitch(card, text="Включить  («Джарвис, какую игру мне поиграть?»)",
                                   font=_font(), progress_color=ACCENT)
        self.sw_ai.grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=5)
        if a["enabled"]:
            self.sw_ai.select()

        self.om_prov = ctk.CTkOptionMenu(
            card, values=list(self._ai_labels.values()), command=self._ai_provider_changed, width=300,
            height=32, font=_font(), dropdown_font=_font(), fg_color=GHOST_H, button_color=ACCENT,
            button_hover_color=ACCENT_H)
        self.om_prov.set(self._ai_labels[self._ai_prov])
        self._field(card, 2, "Провайдер", self.om_prov)
        self.om_prov.grid_configure(sticky="w")
        _button(card, "Получить ключ", self._ai_open_key_page, width=130).grid(row=2, column=2, padx=(0, 16))

        self.v_ai_key = _entry(card, a["api_key"], placeholder="вставь API-ключ (Ctrl+V)")
        self.v_ai_key.configure(show="•")
        self._field(card, 3, "API-ключ", self.v_ai_key)
        self.v_ai_model = _entry(card, a["model"] or pre["model"], width=300)
        self._field(card, 4, "Модель", self.v_ai_model, "если ответ «модель не найдена» — поменяй")
        self.v_ai_model.grid_configure(sticky="w")
        self.v_ai_base = _entry(card, a["base_url"] or pre["base_url"])
        self._field(card, 5, "Адрес API", self.v_ai_base)
        self.v_ai_city = _entry(card, a["city"], width=200)
        self._field(card, 6, "Город для погоды", self.v_ai_city)
        self.v_ai_city.grid_configure(sticky="w")
        self.v_ai_names = _entry(card, ", ".join(a["names"]), width=300)
        self._field(card, 7, "Обращение к Джарвису", self.v_ai_names, "через запятую")
        self.v_ai_names.grid_configure(sticky="w")
        self.v_ai_user = _entry(card, a.get("user_name", "сэр"), width=200)
        self._field(card, 8, "Как обращаться к тебе", self.v_ai_user, "«сэр», «босс», по имени…")
        self.v_ai_user.grid_configure(sticky="w")
        self._ai_style_labels = {k: v for k, v in AI_STYLES}
        self._ai_style_by_label = {v: k for k, v in AI_STYLES}
        self.om_ai_style = ctk.CTkOptionMenu(
            card, values=[v for _, v in AI_STYLES], width=300,
            height=32, font=_font(), dropdown_font=_font(), fg_color=GHOST_H, button_color=ACCENT,
            button_hover_color=ACCENT_H)
        self.om_ai_style.set(self._ai_style_labels.get(a.get("style", "film"), AI_STYLES[0][1]))
        self._field(card, 9, "Характер ответов", self.om_ai_style)
        self.om_ai_style.grid_configure(sticky="w")
        self.sw_ai_pc = ctk.CTkSwitch(card, text="Рассказывать нейросети про мой ПК (железо, игры Steam)",
                                      font=_font(), progress_color=ACCENT)
        self.sw_ai_pc.grid(row=10, column=0, columnspan=3, sticky="w", padx=16, pady=(8, 5))
        if a.get("pc_context", True):
            self.sw_ai_pc.select()

        self.sw_ai_files = ctk.CTkSwitch(
            card, text="Доступ к файлам ПК: чтение, создание и редактирование файлов и папок",
            font=_font(), progress_color=ACCENT)
        self.sw_ai_files.grid(row=11, column=0, columnspan=3, sticky="w", padx=16, pady=(8, 5))
        if a.get("files", True):
            self.sw_ai_files.select()

        self.sw_ai_self = ctk.CTkSwitch(
            card, text="Разрешить нейросети редактировать самого Джарвиса (его файлы и настройки)",
            font=_font(), progress_color=ACCENT)
        self.sw_ai_self.grid(row=12, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 5))
        if a.get("self_edit", True):
            self.sw_ai_self.select()

        self.sw_ai_refine = ctk.CTkSwitch(
            card, text="Додумывать непонятые фразы: исправлять слова и расставлять запятые",
            font=_font(), progress_color=ACCENT)
        self.sw_ai_refine.grid(row=13, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 5))
        if a.get("refine", True):
            self.sw_ai_refine.select()

        self.sw_hist = ctk.CTkSwitch(card, text="История запросов (файл history.jsonl, команда «история запросов»)",
                                     font=_font(), progress_color=ACCENT)
        self.sw_hist.grid(row=14, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 5))
        if self.cfg.get("history", {}).get("enabled", True):
            self.sw_hist.select()

        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=15, column=0, columnspan=3, sticky="ew", padx=16, pady=(8, 14))
        self.btn_ai_test = _button(bar, "Проверить", self._ai_test, width=110)
        self.btn_ai_test.pack(side="left")
        self.lbl_ai_test = ctk.CTkLabel(bar, text="", font=_font(12), anchor="w", justify="left", wraplength=560)
        self.lbl_ai_test.pack(side="left", padx=(12, 0), fill="x", expand=True)

        info = self._card(sf, "Как это работает", 1)
        ctk.CTkLabel(
            info, font=_font(12), text_color=MUTED, justify="left", anchor="w", wraplength=760,
            text=("1. Нажми «Получить ключ», войди в аккаунт и скопируй ключ. Карта не нужна.\n"
                  "2. Вставь ключ, нажми «Проверить», затем «Сохранить».\n"
                  "3. Скажи «Джарвис, какая сегодня погода?» — ответ придёт голосом и коротко.\n\n"
                  "Нейросеть отвечает только на фразы со словом из «Обращение к Джарвису», чтобы разговоры рядом "
                  "не тратили лимит. Команды вроде «открой ютуб» работают как раньше.\n\n"
                  "Доступ к файлам: если включено, нейросеть читает, создаёт и меняет файлы на ПК (и сам "
                  "Джарвис) через инструменты list_dir / read_file / write_file / edit_file. Системные папки "
                  "Windows править нельзя, перед правкой создаётся копия .bak. Все запросы пишутся в "
                  "историю (%USERPROFILE%\\.jarvis\\history.jsonl).\n\n"
                  "Приватность: вопросы и данные о ПК (если включено) уходят провайдеру. У бесплатного Gemini "
                  "вне ЕС запросы могут использоваться для обучения моделей. Ключ хранится в "
                  "%USERPROFILE%\\.jarvis\\config.json открытым текстом. Не выкладывай этот файл.")
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))

    def _ai_provider_changed(self, label: str) -> None:
        new = self.ai.PRESETS[self._ai_by_label[label]]
        self._ai_prov = self._ai_by_label[label]
        if self._ai_prov == "custom":  # «свой»: оставляем, что есть, пользователь впишет адрес и модель сам
            return
        for entry, key in ((self.v_ai_model, "model"), (self.v_ai_base, "base_url")):
            entry.delete(0, "end")  # модель и адрес чужого провайдера новому не подходят
            entry.insert(0, new[key])

    def _ai_open_key_page(self) -> None:
        url = self.ai.PRESETS[self._ai_prov]["key_url"]
        if url:
            webbrowser.open(url)

    def _ai_form(self) -> dict:
        pre = self.ai.PRESETS[self._ai_prov]
        model, base = self.v_ai_model.get().strip(), self.v_ai_base.get().strip()
        return {
            "enabled": bool(self.sw_ai.get()),
            "provider": self._ai_prov,
            "api_key": self.v_ai_key.get().strip(),
            "model": "" if model == pre["model"] else model,       # как у пресета — не фиксируем
            "base_url": "" if base == pre["base_url"] else base,
            "city": self.v_ai_city.get().strip() or "Днепр",
            "names": [n for n in (_norm(x) for x in self.v_ai_names.get().split(",")) if n] or ["джарвис"],
            "user_name": self.v_ai_user.get().strip() or "сэр",
            "style": self._ai_style_by_label.get(self.om_ai_style.get(), "film"),
            "pc_context": bool(self.sw_ai_pc.get()),
            "files": bool(self.sw_ai_files.get()),
            "self_edit": bool(self.sw_ai_self.get()),
            "refine": bool(self.sw_ai_refine.get()),
        }

    def _ai_test(self) -> None:
        self.lbl_ai_test.configure(text="Проверяю…", text_color=MUTED)
        self.btn_ai_test.configure(state="disabled")
        form, box = dict(self.cfg["ai"], **self._ai_form()), {}

        def work():
            box["res"] = self.ai.test_connection(form)

        threading.Thread(target=work, daemon=True).start()

        def poll():
            try:
                if "res" not in box:
                    self.win.after(200, poll)
                    return
                ok, msg = box["res"]
                self.btn_ai_test.configure(state="normal")
                self.lbl_ai_test.configure(text=("✓ Работает. Ответ: " if ok else "✗ ") + msg,
                                           text_color=OK_COLOR if ok else ERR_COLOR)
            except tk.TclError:
                pass

        poll()

    def _build_paths(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, wraplength=760, justify="left", anchor="w", font=_font(12), text_color=MUTED,
                     text="Обычно трогать не нужно: Джарвис ищет программы сам. Заполняй, только если команда "
                          "пишет «не нашёл». Пустое поле — автопоиск.").grid(row=0, column=0, sticky="w", padx=4, pady=(0, 8))
        card = self._card(tab, "Пути к программам", 1)
        self.v_paths = {}
        for i, (key, label, hint) in enumerate(PATH_LABELS, start=1):
            e = self.v_paths[key] = _entry(card, self.cfg["paths"].get(key) or "", placeholder=hint)
            self._field(card, i, label, e)
            _button(card, "Обзор…", lambda e=e: self._browse(e), width=90).grid(
                row=i, column=2, padx=(0, 16))
        ctk.CTkFrame(card, fg_color="transparent", height=8).grid(row=len(PATH_LABELS) + 1, column=0)

    def _build_security(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        sec = self.cfg.get("security", {})
        card = self._card(tab, "Подтверждения и парольная фраза", 0)
        self.sw_confirm = ctk.CTkSwitch(card, text="Запрашивать подтверждение опасных действий", font=_font())
        if sec.get("confirm_dangerous", True): self.sw_confirm.select()
        self._field(card, 1, "Подтверждения", self.sw_confirm,
                    "Выключение, сон, удаление, сообщения и жёсткое закрытие процессов.")
        self.v_password = _entry(card, "", width=300, placeholder="Оставь пустым, чтобы не менять")
        self.v_password.configure(show="•")
        self._field(card, 2, "Новая парольная фраза", self.v_password,
                    "Хранится только salted SHA-256 хеш. Это защита от случайных срабатываний, не биометрия.")

    def _build_notifications(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        n = self.cfg.get("notifications", {})
        card = self._card(tab, "Всплывающие уведомления", 0)
        self.v_notif_pos = ctk.StringVar(value=str(n.get("position", "bottom_right")))
        self.v_notif_theme = ctk.StringVar(value=str(n.get("theme", "dark")))
        self.v_notif_duration = _entry(card, str(n.get("duration_ms", 5000)), width=130)
        self.v_notif_font = _entry(card, str(n.get("font_size", 14)), width=130)
        pos = ctk.CTkOptionMenu(card, variable=self.v_notif_pos, values=["bottom_right", "bottom_left", "top_right", "top_left"], width=200)
        theme = ctk.CTkOptionMenu(card, variable=self.v_notif_theme, values=["dark", "light", "minimal"], width=200)
        self._field(card, 1, "Позиция", pos)
        self._field(card, 2, "Тема", theme)
        self._field(card, 3, "Длительность, мс", self.v_notif_duration)
        self._field(card, 4, "Размер шрифта", self.v_notif_font)

    def _build_integrations(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        ic = self.cfg.get("integrations", {})
        card = self._card(tab, "Интеграции и разработка", 0)
        self.v_city = _entry(card, str(ic.get("weather_city", "")), width=260, placeholder="Город")
        self.v_lat = _entry(card, str(ic.get("latitude", "")), width=130, placeholder="широта")
        self.v_lon = _entry(card, str(ic.get("longitude", "")), width=130, placeholder="долгота")
        self.v_hotkey = _entry(card, str(ic.get("hotkey", "ctrl+alt+j")), width=180)
        self.v_test_project = _entry(card, str(ic.get("test_project", "")), width=300, placeholder="путь к проекту")
        self.v_test_command = _entry(card, str(ic.get("test_command", "pytest")), width=220)
        self.v_telegram_token = _entry(card, str(ic.get("telegram_token", "")), width=300, placeholder="токен Telegram-бота")
        self.v_telegram_token.configure(show="•")
        self.v_discord_hooks = _entry(card, json.dumps(ic.get("discord_webhooks", {}), ensure_ascii=False), width=300, placeholder='{"канал": "webhook"}')
        self._field(card, 1, "Город", self.v_city)
        self._field(card, 2, "Координаты", self.v_lat, "Укажи широту; долготу задай в поле справа")
        self.v_lon.grid(row=2, column=2, sticky="w", padx=(0, 18), pady=6)
        self._field(card, 3, "Горячая клавиша", self.v_hotkey, "Например: ctrl+alt+j.")
        self._field(card, 4, "Проект для тестов", self.v_test_project)
        self._field(card, 5, "Команда тестов", self.v_test_command)
        self._field(card, 6, "Токен Telegram", self.v_telegram_token, "Секрет маскируется. При отсутствии keyring хранится в config.json.")
        self._field(card, 7, "Discord webhooks JSON", self.v_discord_hooks)

    def _build_dictation(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        dc = self.cfg.get("dictation", {})
        card = self._card(tab, "Ввод текста в активное окно", 0)
        self.v_dict_method = ctk.StringVar(value=str(dc.get("method", "auto")))
        self.v_dict_delay = _entry(card, str(dc.get("char_delay_ms", 8)), width=120)
        self.v_dict_timeout = _entry(card, str(dc.get("idle_timeout_sec", 120)), width=120)
        self.v_dict_blacklist = _entry(card, ", ".join(dc.get("blacklist", [])), width=340)
        self.sw_dict_format = ctk.CTkSwitch(card, text="Автоформатирование знаков и регистра", font=_font())
        self.sw_dict_confirm = ctk.CTkSwitch(card, text="Подтверждать ввод в неизвестное окно", font=_font())
        self.sw_dict_indicator = ctk.CTkSwitch(card, text="Показывать индикатор режима диктовки", font=_font())
        if dc.get("autoformat", True): self.sw_dict_format.select()
        if dc.get("confirm_unknown", False): self.sw_dict_confirm.select()
        if dc.get("indicator", True): self.sw_dict_indicator.select()
        method = ctk.CTkOptionMenu(card, variable=self.v_dict_method, values=["auto", "unicode", "clipboard"], width=180)
        self._field(card, 1, "Способ ввода", method, "Авто: Unicode SendInput, а для терминалов и длинного текста — буфер.")
        self._field(card, 2, "Задержка символов, мс", self.v_dict_delay)
        self._field(card, 3, "Выход по тишине, с", self.v_dict_timeout)
        self._field(card, 4, "Чёрный список окон", self.v_dict_blacklist)
        self._field(card, 5, "Правила текста", self.sw_dict_format)
        self._field(card, 6, "Неизвестное окно", self.sw_dict_confirm)
        self._field(card, 7, "Индикатор", self.sw_dict_indicator)

    def _build_history(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        card = self._card(tab, "История распознанных запросов", 0)
        self.v_history_search = _entry(card, "", width=280, placeholder="поиск по тексту")
        self._field(card, 1, "Поиск", self.v_history_search)
        _button(card, "Найти", self._refresh_history, width=90).grid(row=1, column=2, sticky="w", padx=(0, 16))
        self.history_box = ctk.CTkTextbox(card, width=700, height=280, font=_font(12), wrap="word")
        self.history_box.grid(row=2, column=0, columnspan=3, sticky="ew", padx=18, pady=(10, 8))
        self.v_history_run = _entry(card, "", width=420, placeholder="фраза для повторного выполнения")
        self._field(card, 3, "Повторить", self.v_history_run)
        _button(card, "Выполнить снова", self._history_run, "accent", 150).grid(row=3, column=2, sticky="w", padx=(0, 16))
        _button(card, "Очистить историю", self._history_clear, "danger", 150).grid(row=4, column=1, sticky="w", padx=(0, 12), pady=(8, 14))
        self._refresh_history()

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_box"):
            return
        query = self.v_history_search.get().strip() if hasattr(self, "v_history_search") else ""
        rows = self.history_read(query) if self.history_read else []
        self.history_box.delete("1.0", "end")
        if not rows:
            self.history_box.insert("end", "История пуста.")
            return
        for r in rows[:100]:
            text = str(r.get("question") or r.get("text") or "")
            self.history_box.insert("end", f"{r.get('time', '')}  [{r.get('type', '')}]\n{text}\n→ {r.get('answer', '')}\n\n")
        first = str(rows[0].get("question") or "")
        if first:
            self.v_history_run.delete(0, "end")
            self.v_history_run.insert(0, first)

    def _history_run(self) -> None:
        text = self.v_history_run.get().strip()
        if not text or not self.history_run:
            return
        self.history_run(text)
        self._set_status("Команда отправлена на выполнение ✓", OK_COLOR)

    def _history_clear(self) -> None:
        if not self.history_clear:
            return
        ask(self.win, "Очистить историю", "Удалить всю историю запросов?", on_yes=lambda: (self.history_clear(), self._refresh_history()), danger=True)

    def _browse(self, entry) -> None:
        p = filedialog.askopenfilename(parent=self.win, title="Выбери файл")
        if p:
            entry.delete(0, "end")
            entry.insert(0, p.replace("/", "\\"))

    # --- автозапуск -----------------------------------------------------------
    def _auto_toggled(self) -> None:
        on = bool(self.sw_auto.get())
        self.sw_admin.configure(state="normal" if on else "disabled")
        if not on:
            self.sw_admin.deselect()

    def _refresh_auto_label(self, st) -> None:
        name = self.autostart.TASK_NAME
        if st is None:
            text = f"Задача «{name}» не создана.\nЗапускалось бы: {self.autostart.target_text()}"
        else:
            text = (f"Задача «{name}» создана ({'администратор' if st['admin'] else 'обычные права'}).\n"
                    f"Запускает: {st['command']}")
            if self._auto_stale:
                text += "\n⚠ Задача указывает на другой файл — нажми «Сохранить», чтобы обновить путь."
        self.lbl_auto.configure(text=text)

    def _apply_autostart(self) -> None:
        if self.autostart is None:
            self._set_status("Сохранено и применено ✓", OK_COLOR)
            return
        enabled = bool(self.sw_auto.get())
        want = (enabled, enabled and bool(self.sw_admin.get()))
        if want == self._auto0 and not (self._auto_stale and enabled):
            self._set_status("Сохранено и применено ✓", OK_COLOR)
            return
        self._set_status("Настраиваю автозапуск… (может появиться запрос UAC)", MUTED)
        self.btn_save.configure(state="disabled")
        box: dict = {}

        def work():
            try:
                box["res"] = self.autostart.apply(*want)
            except Exception as e:  # noqa: BLE001
                box["res"] = (False, str(e))

        threading.Thread(target=work, daemon=True).start()

        def poll():
            try:
                if "res" not in box:
                    self.win.after(200, poll)
                    return
                ok, msg = box["res"]
                self.btn_save.configure(state="normal")
                if ok:
                    self._auto0, self._auto_stale = want, False
                    self._refresh_auto_label(self.autostart.status())
                    self._set_status("Сохранено и применено ✓  " + msg, OK_COLOR)
                else:
                    self._set_status("Настройки сохранены, но автозапуск не настроен: " + msg, ERR_COLOR)
            except tk.TclError:
                pass  # окно закрыли, пока шла настройка

        poll()

    # --- сохранение --------------------------------------------------------
    def _set_status(self, text: str, color: str) -> None:
        self.status.configure(text=text, text_color=color)

    def _collect(self) -> dict:
        try:
            delay = int(self.v_delay.get().strip())
            if not 0 <= delay <= 600:
                raise ValueError
        except ValueError:
            raise ValueError("Задержка выключения — число от 0 до 600.")
        wake = _norm(self.v_wake.get())
        if self.sw_wake.get() and not wake:
            raise ValueError("Укажи слово-активатор или выключи опцию.")
        phrases = {k: _norm(v.get()) for k, v in self.v_phr.items()}
        if not all(phrases.values()):
            raise ValueError("Фразы управления не должны быть пустыми.")
        patch_ai = {}
        if self.ai is not None:
            patch_ai = {"ai": self._ai_form()}
            if patch_ai["ai"]["enabled"] and not self.ai.resolve(patch_ai["ai"])[2]:
                raise ValueError("Вставь API-ключ на вкладке «Нейросеть» или выключи нейросеть.")
        patch = {
            **patch_ai,
            "commands": [{"phrase": p, "target": t} for p, t in self.t_cmd.rows()],
            "games": {p: int(a) for p, a in self.t_games.rows()},
            "sites": {p: u for p, u in self.t_sites.rows()},
            "urls": {k: (v.get().strip() or None) for k, v in self.v_urls.items()},
            "voice": {"enabled": bool(self.sw_voice.get()),
                      "engine": "piper" if self.v_engine.get().startswith("piper") else "sapi",
                      "piper_voice": self.v_piper.get().split(" ")[0].lower() or "dmitri"},
            "shutdown_delay_sec": delay,
            "wake_word": {"enabled": bool(self.sw_wake.get()), "word": wake or "джарвис"},
            "chrome": {"main_profile": self.v_prof_main.get().strip() or "Default",
                       "study_profile": self.v_prof_study.get().strip() or None},
            "genshin_task": self.v_task.get().strip() or None,
            "phrases": phrases,
            "paths": {k: v.get().strip() for k, v in self.v_paths.items() if v.get().strip()},
            "security": {"confirm_dangerous": bool(self.sw_confirm.get())},
            "notifications": {"position": self.v_notif_pos.get(), "theme": self.v_notif_theme.get(),
                              "duration_ms": self._int_field(self.v_notif_duration, "Длительность", 500, 30000),
                              "font_size": self._int_field(self.v_notif_font, "Размер шрифта", 9, 28)},
            "integrations": self._integration_form(),
            "dictation": {"method": self.v_dict_method.get(),
                          "char_delay_ms": self._int_field(self.v_dict_delay, "Задержка символов", 1, 100),
                          "idle_timeout_sec": self._int_field(self.v_dict_timeout, "Таймаут диктовки", 10, 3600),
                          "blacklist": [x.strip().lower() for x in self.v_dict_blacklist.get().split(",") if x.strip()],
                          "autoformat": bool(self.sw_dict_format.get()),
                          "confirm_unknown": bool(self.sw_dict_confirm.get()),
                          "indicator": bool(self.sw_dict_indicator.get())},
        }
        phrase = self.v_password.get().strip()
        if phrase:
            salt = secrets.token_hex(16)
            patch["security"].update({"password_salt": salt,
                "password_hash": hashlib.sha256((salt + phrase.lower()).encode("utf-8")).hexdigest()})
        sw_hist = getattr(self, "sw_hist", None)  # вкладка «Нейросеть» есть не всегда
        if sw_hist is not None:
            hist = self.cfg.get("history", {})
            patch["history"] = {"enabled": bool(sw_hist.get()), "max": int(hist.get("max") or 300)}
        return patch

    @staticmethod
    def _int_field(entry, label: str, low: int, high: int) -> int:
        try:
            n = int(entry.get().strip())
        except ValueError:
            raise ValueError(f"{label} — целое число от {low} до {high}.") from None
        if not low <= n <= high:
            raise ValueError(f"{label} — целое число от {low} до {high}.")
        return n

    def _integration_form(self) -> dict:
        try:
            hooks = json.loads(self.v_discord_hooks.get().strip() or "{}")
            if not isinstance(hooks, dict):
                raise ValueError
        except ValueError:
            raise ValueError("Discord webhooks — JSON-объект вида {\"канал\": \"webhook\"}.") from None
        old = self.cfg.get("integrations", {})
        return {"weather_city": self.v_city.get().strip(), "latitude": self.v_lat.get().strip(),
                "longitude": self.v_lon.get().strip(), "hotkey": self.v_hotkey.get().strip() or "ctrl+alt+j",
                "test_project": self.v_test_project.get().strip(),
                "test_command": self.v_test_command.get().strip() or "pytest",
                "telegram_token": self.v_telegram_token.get().strip() or old.get("telegram_token", ""),
                "discord_webhooks": hooks, "translation_language": old.get("translation_language", "английский"),
                "telegram_contacts": old.get("telegram_contacts", {}),
                "daily_reminders": old.get("daily_reminders", []),
                "test_timeout_sec": old.get("test_timeout_sec", 300)}

    def save(self) -> None:
        try:
            patch = self._collect()
            self.on_save(patch)
        except ValueError as e:
            self._set_status(str(e), ERR_COLOR)
            ask(self.win, "Проверь настройки", str(e))
            return
        except Exception as e:  # noqa: BLE001
            self._set_status("Не удалось сохранить", ERR_COLOR)
            ask(self.win, "Не удалось сохранить", str(e))
            return
        self._apply_autostart()