"""Окно настроек Джарвиса (customtkinter).

Открывается голосовой командой «открой настройки». Работает в Tk-потоке Джарвиса
(как дочернее окно его скрытого корня), поэтому отдельного mainloop не создаёт.
Само окно ничего не пишет на диск: по «Сохранить» оно собирает словарь-патч
и отдаёт его в on_save(patch) — сохранением и применением занимается jarvis.py.

Автозапуск через Планировщик заданий тоже делает jarvis.py: сюда передаётся объект
autostart с методами status(), apply(enabled, admin) и target_text().
"""
from __future__ import annotations

import re
import sys
import threading
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

# --- оформление -------------------------------------------------------------
FONT = "Segoe UI"
ACCENT, ACCENT_H = "#1aa6c9", "#1688a6"
DANGER, DANGER_H = "#c94a4a", "#a33a3a"
OK_COLOR, ERR_COLOR, MUTED = "#3ecf8e", "#ff6b6b", "#8b97a6"
CARD, ROW_A, ROW_B = "#1c232d", "#181e26", "#1e2631"
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

def open_settings(root, cfg: dict, on_save, autostart=None) -> None:
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
    _instance = SettingsWindow(root, cfg, on_save, autostart)


class SettingsWindow:
    def __init__(self, root, cfg: dict, on_save, autostart=None):
        self.cfg, self.on_save, self.autostart = cfg, on_save, autostart
        w = self.win = ctk.CTkToplevel(root)
        w.title("Джарвис — настройки")
        w.geometry("940x700")
        w.minsize(800, 580)
        _set_icon(w)

        head = ctk.CTkFrame(w, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(16, 6))
        ctk.CTkLabel(head, text="Джарвис", font=_font(24, True)).pack(side="left")
        ctk.CTkLabel(head, text="настройки применяются сразу после сохранения", font=_font(12),
                     text_color=MUTED).pack(side="left", padx=(12, 0), pady=(8, 0))

        tabs = self.tabs = ctk.CTkTabview(
            w, corner_radius=12, segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_H,
            segmented_button_unselected_hover_color=GHOST_H)
        tabs._segmented_button.configure(font=_font(13, True))
        tabs.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        t = {name: tabs.add(name) for name in
             ("Мои команды", "Игры Steam", "Сайты", "Ссылки", "Общие", "Пути")}

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
        self._build_paths(t["Пути"])

        self.t_cmd.load((c["phrase"], c["target"]) for c in cfg["commands"])
        self.t_games.load(sorted(cfg["games"].items()))
        self.t_sites.load(sorted(cfg["sites"].items()))

        bottom = ctk.CTkFrame(w, fg_color="transparent")
        bottom.pack(fill="x", padx=22, pady=(4, 16))
        self.status = ctk.CTkLabel(bottom, text="", font=_font(13), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        _button(bottom, "Закрыть", w.destroy, width=100).pack(side="right")
        self.btn_save = _button(bottom, "Сохранить", self.save, "accent", 120)
        self.btn_save.pack(side="right", padx=(0, 8))
        w.bind("<Control-s>", lambda e: self.save())

        w.lift()
        w.focus_force()

    # --- вкладки ---------------------------------------------------------
    @staticmethod
    def _card(parent, title: str, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        card.grid(row=row, column=0, sticky="ew", padx=4, pady=(0, 10))
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=title, font=_font(14, True), text_color=ACCENT).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(12, 6))
        return card

    @staticmethod
    def _field(card, r: int, label: str, entry, note: str = "") -> None:
        ctk.CTkLabel(card, text=label, font=_font(), anchor="w").grid(
            row=r, column=0, sticky="w", padx=(16, 12), pady=5)
        entry.grid(row=r, column=1, sticky="ew", padx=(0, 16), pady=5)
        if note:
            ctk.CTkLabel(card, text=note, font=_font(11), text_color=MUTED).grid(
                row=r, column=2, sticky="w", padx=(0, 16))

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
        self.v_delay = _entry(card, str(c["shutdown_delay_sec"]), width=80)
        self._field(card, 2, "Задержка выключения / перезагрузки", self.v_delay, "секунд, от 0 до 600")
        self.v_delay.grid_configure(sticky="w")
        ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=3, column=0)

        # --- слово-активатор
        card = self._card(sf, "Слово-активатор", 1)
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
        card = self._card(sf, "Chrome", 2)
        self.v_prof_main = _entry(card, c["chrome"]["main_profile"] or "Default", width=200)
        self.v_prof_study = _entry(card, c["chrome"]["study_profile"] or "", width=200, placeholder="как основной")
        self._field(card, 1, "Профиль основной", self.v_prof_main, "папка профиля: Default, Profile 1…")
        self._field(card, 2, "Профиль учебный", self.v_prof_study)
        self.v_prof_main.grid_configure(sticky="w")
        self.v_prof_study.grid_configure(sticky="w")
        ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=3, column=0)

        # --- планировщик
        card = self._card(sf, "Планировщик заданий Windows", 3)
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
        card = self._card(sf, "Фразы управления", 4)
        self.v_phr = {}
        for i, (key, label) in enumerate(PHRASE_LABELS, start=1):
            self.v_phr[key] = _entry(card, c["phrases"][key], width=320)
            self._field(card, i, label, self.v_phr[key])
            self.v_phr[key].grid_configure(sticky="w")
        ctk.CTkFrame(card, fg_color="transparent", height=6).grid(row=len(PHRASE_LABELS) + 1, column=0)

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
        return {
            "commands": [{"phrase": p, "target": t} for p, t in self.t_cmd.rows()],
            "games": {p: int(a) for p, a in self.t_games.rows()},
            "sites": {p: u for p, u in self.t_sites.rows()},
            "urls": {k: (v.get().strip() or None) for k, v in self.v_urls.items()},
            "voice": {"enabled": bool(self.sw_voice.get())},
            "shutdown_delay_sec": delay,
            "wake_word": {"enabled": bool(self.sw_wake.get()), "word": wake or "джарвис"},
            "chrome": {"main_profile": self.v_prof_main.get().strip() or "Default",
                       "study_profile": self.v_prof_study.get().strip() or None},
            "genshin_task": self.v_task.get().strip() or None,
            "phrases": phrases,
            "paths": {k: v.get().strip() for k, v in self.v_paths.items() if v.get().strip()},
        }

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
