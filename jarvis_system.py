"""Системное управление ПК: громкость, яркость, питание, окна, процессы,
скриншот, звук, медиаклавиши, ввод текста, горячая клавиша.

Windows-библиотеки (pycaw, psutil, screen_brightness_control, win32gui, comtypes)
импортируются ВНУТРИ функций — модуль импортируется без них (только ctypes),
а сбой одной функции не ломает остальные. Все ошибки — ActionError с текстом
для озвучки; вызывающий код ловит их и пишет в errors.log.
"""
from __future__ import annotations

import ctypes
import os
import queue
import re
import subprocess
import threading
import time
from ctypes import wintypes


class ActionError(Exception):
    """Сбой действия с понятным человеку объяснением (её озвучивает jarvis.py)."""


def _run_hidden(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout)


# ============================================================================
#  Громкость (pycaw, запасной вариант — клавиши громкости)
# ============================================================================

def _endpoint_volume():
    """IAudioEndpointVolume системного динамика или None (pycaw не установлен)."""
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        return None
    try:
        dev = AudioUtilities.GetSpeakers()
        vol = getattr(dev, "EndpointVolume", None)  # pycaw >= 2024
        if vol is not None:
            return vol
    except Exception:
        pass
    try:  # старый API: Activate -> указатель
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        dev = AudioUtilities.GetSpeakers()
        iface = dev._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))
    except Exception:
        return None


VK_VOLUME_UP, VK_VOLUME_DOWN, VK_VOLUME_MUTE = 0xAF, 0xAE, 0xAD


def _press_key(vk: int) -> None:
    """Клавиша через keybd_event (запасной способ, работает без pycaw)."""
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP


def volume_get() -> int:
    vol = _endpoint_volume()
    if vol is None:
        raise ActionError("Для чтения громкости нужен pycaw: pip install pycaw")
    try:
        return int(round(vol.GetMasterVolumeLevelScalar() * 100))
    except Exception as e:  # noqa: BLE001
        raise ActionError(f"не смог прочитать громкость: {e}") from e


def volume_set(percent: int) -> int:
    """Поставить громкость 0–100. Возвращает новое значение."""
    percent = max(0, min(100, int(percent)))
    vol = _endpoint_volume()
    if vol is None:
        # запасной вариант: колёсико не подойдёт — шлём максимум/минимум шагами
        raise ActionError("Для точной установки громкости нужен pycaw: pip install pycaw")
    try:
        vol.SetMasterVolumeLevelScalar(percent / 100.0, None)
        return percent
    except Exception as e:  # noqa: BLE001
        raise ActionError(f"не смог поставить громкость: {e}") from e


def volume_change(delta: int) -> int:
    """Изменить громкость на delta процентных пунктов. Возвращает новое значение."""
    try:
        current = volume_get()
    except ActionError:
        # pycaw нет — шлём системные клавиши громкости (шаг 2% * n)
        steps = max(1, min(25, abs(int(delta)) // 5))
        key = VK_VOLUME_UP if delta > 0 else VK_VOLUME_DOWN
        for _ in range(steps):
            _press_key(key)
            time.sleep(0.03)
        raise ActionError("Громкость изменена клавишами — точное значение недоступно без pycaw")
    return volume_set(current + delta)


def volume_mute(state: bool | None = None) -> bool:
    """Выключить/включить звук; state=None — переключить. Возвращает новое состояние."""
    vol = _endpoint_volume()
    if vol is None:
        _press_key(VK_VOLUME_MUTE)
        raise ActionError("Звук переключён клавишей Mute (pycaw не установлен)")
    try:
        muted = bool(vol.GetMute())
        new = (not muted) if state is None else bool(state)
        vol.SetMute(1 if new else 0, None)
        return new
    except Exception as e:  # noqa: BLE001
        raise ActionError(f"не смог переключить звук: {e}") from e


# ============================================================================
#  Яркость (screen_brightness_control; внешние мониторы часто не поддерживают)
# ============================================================================

def brightness_get() -> int:
    try:
        import screen_brightness_control as sbc
    except ImportError:
        raise ActionError("Для яркости нужен screen_brightness_control: "
                          "pip install screen_brightness_control") from None
    try:
        val = sbc.get_brightness(display=0)
        if isinstance(val, list):
            val = val[0]
        return int(val)
    except Exception as e:  # noqa: BLE001
        raise ActionError("Не смог прочитать яркость: этот монитор (внешний) "
                          "управление яркостью не поддерживает") from e


def brightness_set(percent: int) -> int:
    percent = max(0, min(100, int(percent)))
    try:
        import screen_brightness_control as sbc
    except ImportError:
        raise ActionError("Для яркости нужен screen_brightness_control: "
                          "pip install screen_brightness_control") from None
    try:
        sbc.set_brightness(percent, display=0)
        return percent
    except Exception as e:  # noqa: BLE001
        raise ActionError("Не смог изменить яркость: этот монитор (внешний) "
                          "управление яркостью не поддерживает") from e


def brightness_change(delta: int) -> int:
    return brightness_set(brightness_get() + delta)


# ============================================================================
#  Питание: блокировка, сон, гибернация
# ============================================================================

def lock_pc() -> None:
    if ctypes.windll.user32.LockWorkStation() == 0:
        raise ActionError("Не смог заблокировать ПК")


def sleep_pc() -> None:
    # SetSuspendState(0,0,0) — обычный сон (если включена гибернация, вызов её не сделает)
    rc = ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
    if rc == 0:
        raise ActionError("Не удалось уйти в сон (проверь, не отключена ли гибернация)")


def hibernate_pc() -> None:
    rc = ctypes.windll.powrprof.SetSuspendState(1, 0, 0)
    if rc == 0:
        raise ActionError("Гибернация не включена: powercfg /h on в терминале от администратора")


# ============================================================================
#  Процессы: топ и закрытие приложений
# ============================================================================

# Системные процессы, которых касаться нельзя (чёрный список)
SYSTEM_PROCESSES = frozenset({
    "csrss.exe", "smss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "svchost.exe", "system", "registry", "memory compression",
    "dwm.exe", "fontdrvhost.exe", "sihost.exe", "taskhostw.exe",
    "explorer.exe", "conhost.exe", "audiodg.exe", "dismhost.exe",
    "runtimebroker.exe", "searchindexer.exe", "securityhealthservice.exe",
})


def top_processes(limit: int = 5) -> list[dict]:
    """Топ процессов по CPU и RAM: [{name, cpu, ram_mb}] (psutil)."""
    try:
        import psutil
    except ImportError:
        raise ActionError("Для списка процессов нужен psutil: pip install psutil") from None
    procs = []
    try:
        for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                name = str(info.get("name") or "?")
                if not info.get("memory_info"):
                    continue
                procs.append({"name": name,
                              "cpu": float(info.get("cpu_percent") or 0.0),
                              "ram_mb": info.memory_info.rss / (1024 * 1024)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:  # noqa: BLE001
        raise ActionError(f"не смог получить список процессов: {e}") from e
    by_cpu = sorted(procs, key=lambda r: -r["cpu"])[:limit]
    by_ram = sorted(procs, key=lambda r: -r["ram_mb"])[:limit]
    # склеиваем, дедуплицируя по имени
    out, seen = [], set()
    for row in by_cpu + by_ram:
        key = row["name"].lower()
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out[:limit * 2]


def find_process(name_query: str) -> list:
    """Процессы по имени exe (русские названия -> exe через alias-таблицу)."""
    try:
        import psutil
    except ImportError:
        raise ActionError("Нужен psutil: pip install psutil") from None
    name_query = (name_query or "").strip().lower()
    hits = []
    for p in psutil.process_iter(["name", "pid"]):
        try:
            name = str(p.info.get("name") or "")
            if name_query and name_query in name.lower():
                hits.append(p)
        except Exception:  # noqa: BLE001, S110
            continue
    return hits


# ---------------------------------------------------------------------------
#  Закрытие окон по запросу пользователя (заголовок / exe / активное окно)
# ---------------------------------------------------------------------------

# Защита: эти окна по голосовой просьбе не закрываем
PROTECTED_TITLES = ("джарвис", "jarvis")


def visible_windows(limit: int = 200) -> list[tuple[int, str]]:
    """[(hwnd, заголовок)] — видимые окна с непустым заголовком."""
    import win32gui

    out: list[tuple[int, str]] = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if title:
                out.append((hwnd, title))
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:  # noqa: BLE001, S110
        pass
    return out[:limit]


def open_window_titles(limit: int = 5) -> list[str]:
    """Топ-заголовков для сообщения «Открытые окна: …»."""
    return [t for _, t in visible_windows(limit)]


def _send_wm_close(hwnd: int) -> None:
    """WM_CLOSE окну; для UWP (ApplicationFrameHost) — ещё и дочернему окну приложения."""
    import psutil
    import win32con
    import win32gui

    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    try:
        _, pid = win32gui.GetWindowThreadProcessId(hwnd)
        pname = (psutil.Process(pid).name() or "").lower()
    except Exception:  # noqa: BLE001, S110
        return
    if pname != "applicationframehost.exe":
        return
    # UWP: приложение живёт в своём процессе, фрейм — только обёртка:
    # WM_CLOSE дочернему окну реального приложения.
    children: list[int] = []
    try:
        win32gui.EnumChildWindows(hwnd, lambda h, _: children.append(h) or True, None)
    except Exception:  # noqa: BLE001, S110
        return
    for child in children:
        try:
            _, cpid = win32gui.GetWindowThreadProcessId(child)
            if cpid != pid:
                win32gui.PostMessage(child, win32con.WM_CLOSE, 0, 0)
        except Exception:  # noqa: BLE001, S110
            continue


def window_is_elevated(hwnd: int) -> bool:
    """Окно запущено от администратора — WM_CLOSE от обычного процесса не пройдёт."""
    try:
        import ctypes
        import ctypes.wintypes as wt
        import win32gui

        PROCESS_QUERY_LIMITED = 0x1000
        TOKEN_QUERY = 0x0008
        _, pid = win32gui.GetWindowThreadProcessId(hwnd)
        hproc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
        if not hproc:
            return False
        try:
            token = ctypes.c_void_p()
            if not ctypes.windll.advapi32.OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(token)):
                return False
            try:
                elevation = wt.DWORD()
                size = wt.DWORD(ctypes.sizeof(elevation))
                ok = ctypes.windll.advapi32.GetTokenInformation(
                    token.value, 20, ctypes.byref(elevation), size, ctypes.byref(size))
                return bool(ok and elevation.value)
            finally:
                ctypes.windll.kernel32.CloseHandle(token)
        finally:
            ctypes.windll.kernel32.CloseHandle(hproc)
    except Exception:  # noqa: BLE001, S110
        return False

_ACTIVE_TARGETS = {"это", "окно", "текущее", "активное", "данное", "сейчас",
                   "это окно", "текущее окно", "активное окно", "данное окно"}


def close_window_by_name(name: str, aliases: dict | None = None) -> dict:
    """Закрыть окно: (1) алиас, (2) заголовок окна, (3) имя exe, (4) активное окно.

    Возвращает {"closed": int, "remaining": int, "pids": [..]}.
    При неудаче — ActionError с понятным сообщением и списком открытых окон,
    а не молчаливое «Завершено процессов: 0».
    """
    import time as _time

    target = (name or "").strip().lower()
    if not target:
        raise ActionError("Не понял, какое окно закрыть.")

    # (4) «закрой это / окно / текущее» — активное окно, с защитой
    if target in _ACTIVE_TARGETS:
        win = active_window()
        if not win["hwnd"]:
            raise ActionError("Нет активного окна — нечего закрывать.")
        title_l = (win["title"] or "").lower()
        if any(p in title_l for p in PROTECTED_TITLES):
            raise ActionError(f"Не буду закрывать окно Джарвиса («{win['title']}»).")
        _send_wm_close(win["hwnd"])
        _time.sleep(0.8)
        try:
            import win32gui
            alive = bool(win32gui.IsWindow(win["hwnd"]))
        except Exception:  # noqa: BLE001, S110
            alive = False
        if not alive:
            return {"closed": 1, "remaining": 0, "pids": [win["pid"]]}
        if window_is_elevated(win["hwnd"]):
            raise ActionError(
                f"Окно «{win['title']}» не закрылось: оно от администратора. "
                "Запусти Джарвиса от администратора, чтобы закрывать такие окна.")
        return {"closed": 0, "remaining": 1, "pids": [win["pid"]]}

    # (1) алиас из настроек: «блокнот» -> notepad.exe
    resolved = ((aliases or {}).get(target) or target).strip()
    words = [w for w in resolved.split() if w and w not in ("окно", "приложение", "программа")]

    # (2) заголовок окна: запрос (или все его слова) есть в заголовке (без учёта регистра).
    # Поддерживаем частичные совпадения: «microsoft» найдёт «Microsoft Store»,
    # «spotify» найдёт «Spotify Premium», «microsoft store» — по подстроке.
    hwnds = [h for h, title in visible_windows()
             if (target in title.lower()
                 or (words and all(w in title.lower() for w in words))
                 or (words and any(w in title.lower() for w in words) and len(words) == 1))
             and not any(p in title.lower() for p in PROTECTED_TITLES)]
    # Если точного/подстрочного совпадения нет — пробуем любое слово (универсальный fallback).
    if not hwnds and words:
        hwnds = [h for h, title in visible_windows()
                 if any(w in title.lower() for w in words)
                 and not any(p in title.lower() for p in PROTECTED_TITLES)]

    # (3) имя exe
    pids = set()
    try:
        pids = {p.pid for p in find_process(resolved)}
    except ActionError:
        pids = set()

    if not hwnds and not pids:
        titles = open_window_titles(5)
        listing = "; ".join(titles) if titles else "ничего не открыто"
        raise ActionError(f"Не нашёл окно «{name}». Открытые окна: {listing}")

    closed = 0
    for hwnd in hwnds:
        _send_wm_close(hwnd)
    if hwnds:
        _time.sleep(1.0)  # даём приложению закрыться штатно (в т.ч. спросить про файлы)
        try:
            import win32gui
            remaining = [h for h in hwnds if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h)]
        except Exception:  # noqa: BLE001, S110
            remaining = []
        if remaining:
            if any(window_is_elevated(h) for h in remaining):
                raise ActionError(
                    f"Окно «{name}» не закрылось: оно от администратора. "
                    "Запусти Джарвиса от администратора, чтобы закрывать такие окна.")
            return {"closed": len(hwnds) - len(remaining), "remaining": len(remaining),
                    "pids": sorted(pids)}
        closed = len(hwnds)
    return {"closed": closed, "remaining": 0, "pids": sorted(pids)}


def kill_pids(pids) -> int:
    """Принудительное завершение процессов по pid (только после подтверждения)."""
    try:
        import psutil
    except ImportError:
        raise ActionError("Нужен psutil: pip install psutil") from None
    killed = 0
    for pid in pids:
        try:
            p = psutil.Process(int(pid))
            if (p.name() or "").lower() in SYSTEM_PROCESSES:
                continue
            p.kill()
            killed += 1
        except Exception:  # noqa: BLE001, S110
            continue
    return killed


def close_process(name: str, force: bool = False) -> int:
    """Мягкое закрытие (WM_CLOSE по окнам), с force=True — убийство процесса.
    Системные процессы (чёрный список) не трогаем. Возвращает, сколько закрыто."""
    name = (name or "").strip().lower()
    if not name:
        raise ActionError("Не указано, что закрывать")
    if name in SYSTEM_PROCESSES:
        raise ActionError(f"«{name}» — системный процесс, закрывать нельзя")
    closed = 0
    if not force:
        try:
            closed = _close_windows_of_process(name)
        except Exception:  # noqa: BLE001, S110
            closed = 0
        if closed:
            return closed
    # жёстко (только после подтверждения — force передаёт вызывающий код)
    import psutil
    for p in find_process(name):
        if p.name().lower() in SYSTEM_PROCESSES:
            continue
        try:
            p.kill()
            closed += 1
        except Exception:  # noqa: BLE001, S110
            continue
    return closed


def _close_windows_of_process(proc_name: str) -> int:
    """WM_CLOSE всем окнам процесса — приложение само спросит про несохранённое."""
    import psutil
    import win32con
    import win32gui

    pids = set()
    for p in find_process(proc_name):
        pids.add(p.pid)

    closed = 0
    result = {"count": 0}

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32gui.GetWindowThreadProcessId(hwnd)
            if pid in pids:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                result["count"] += 1
        except Exception:  # noqa: BLE001, S110
            pass
        return True

    win32gui.EnumWindows(cb, None)
    closed = result["count"]
    if closed:
        time.sleep(0.8)  # даём приложению закрыться штатно
    return closed


# ============================================================================
#  Скриншот (PowerShell + System.Drawing — без сторонних зависимостей)
# ============================================================================

_PSShot = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save($env:JARVIS_SHOT, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"""


def screenshot(dest_dir) -> str:
    """Скриншот всех мониторов в dest_dir/screen-YYYYmmdd-HHMMSS.png.
    Возвращает путь. Копию кладёт в буфер обмена (если получится)."""
    from datetime import datetime
    dest_dir = os.path.expanduser(str(dest_dir))
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"screen-{datetime.now():%Y%m%d-%H%M%S}.png")
    env = dict(os.environ, JARVIS_SHOT=path)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", _PSShot],
            stdin=subprocess.DEVNULL, capture_output=True, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise ActionError(f"не смог сделать скриншот: {e}") from e
    if not os.path.isfile(path):
        err = (r.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise ActionError(f"скриншот не сохранился{': ' + err if err else ''}")
    # копия в буфер обмена (не критично — молчим при сбое)
    try:
        _run_hidden(["powershell", "-NoProfile", "-STA", "-Command",
                     "Add-Type -AssemblyName System.Windows.Forms; "
                     "[System.Windows.Forms.Clipboard]::SetImage("
                     f"[System.Drawing.Image]::FromFile('{path}'))"], timeout=15)
    except Exception:  # noqa: BLE001, S110
        pass
    return path


# ============================================================================
#  Медиаклавиши и «что сейчас играет»
# ============================================================================

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3


def media_key(key: str) -> None:
    """playpause | next | prev — через системные медиаклавиши (работают глобально)."""
    vk = {"playpause": VK_MEDIA_PLAY_PAUSE, "nexttrack": VK_MEDIA_NEXT_TRACK,
          "prevtrack": VK_MEDIA_PREV_TRACK}.get(key)
    if vk is None:
        raise ActionError(f"неизвестная медиаклавиша: {key}")
    _press_key(vk)


def gamebar_record_last() -> None:
    """Win+Alt+G — «Записать последние» в Xbox Game Bar.

    Windows должна разрешать фоновую запись; иначе сама Game Bar покажет причину.
    """
    user32 = ctypes.windll.user32
    VK_LWIN, VK_MENU, VK_G = 0x5B, 0x12, 0x47
    for vk in (VK_LWIN, VK_MENU, VK_G):
        user32.keybd_event(vk, 0, 0, 0)
    for vk in (VK_G, VK_MENU, VK_LWIN):
        user32.keybd_event(vk, 0, 2, 0)


# Заголовки окон известных плееров: подстрока -> подпись
PLAYER_TITLES = (
    ("youtube music", "YouTube Music"),
    ("spotify", "Spotify"),
    ("vlc media player", "VLC"),
    ("foobar", "foobar2000"),
    ("aimp", "AIMP"),
    ("winamp", "Winamp"),
    ("- media player", "Windows Media Player"),
)


def now_playing() -> str | None:
    """Заголовок окна плеера, если он открыт. Иначе None."""
    import win32gui
    titles = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t:
                titles.append(t)
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception as e:  # noqa: BLE001
        raise ActionError(f"не смог просмотреть окна: {e}") from e
    for t in titles:
        low = t.lower()
        for sub, label in PLAYER_TITLES:
            if sub in low:
                # «Track - Artist - YouTube Music» -> «Track - Artist»
                name = re.sub(r"\s*[-–—]\s*" + re.escape(label) + r"\s*$", "", t,
                              flags=re.IGNORECASE).strip()
                return f"{label}: {name}" if name and name.lower() != label.lower() else label
    return None


# ============================================================================
#  Устройства вывода звука и громкость отдельных приложений (pycaw)
# ============================================================================

_ROLE_CONSOLE = 0


def _ipolicy_config():
    """Минимальный IPolicyConfig (undocumented COM) с SetDefaultEndpoint."""
    import comtypes
    from comtypes import COMMETHOD, GUID

    class IPolicyConfig(comtypes.IUnknown):
        _case_insensitive_ = True
        _iid_ = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")
        _methods_ = [
            COMMETHOD([], ctypes.HRESULT, "GetMixFormat"),
            COMMETHOD([], ctypes.HRESULT, "GetDeviceFormat"),
            COMMETHOD([], ctypes.HRESULT, "ResetDeviceFormat"),
            COMMETHOD([], ctypes.HRESULT, "SetDeviceFormat"),
            COMMETHOD([], ctypes.HRESULT, "GetProcessingPeriod"),
            COMMETHOD([], ctypes.HRESULT, "SetProcessingPeriod"),
            COMMETHOD([], ctypes.HRESULT, "GetShareMode"),
            COMMETHOD([], ctypes.HRESULT, "SetShareMode"),
            COMMETHOD([], ctypes.HRESULT, "GetPropertyValue"),
            COMMETHOD([], ctypes.HRESULT, "SetPropertyValue"),
            COMMETHOD([], ctypes.HRESULT, "SetDefaultEndpoint",
                      ("in", ctypes.c_wchar_p, "pszDeviceName"),
                      ("in", ctypes.c_int, "role")),
            COMMETHOD([], ctypes.HRESULT, "SetEndpointVisibility",
                      ("in", ctypes.c_wchar_p, "pszDeviceName"),
                      ("in", ctypes.c_int, "bVisible")),
        ]
    return IPolicyConfig


def list_output_devices() -> list[dict]:
    """[{id, name, is_default}] — активные устройства вывода."""
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        raise ActionError("Нужен pycaw: pip install pycaw") from None
    try:
        all_dev = AudioUtilities.GetAllDevices()
    except Exception as e:  # noqa: BLE001
        raise ActionError(f"не смог получить устройства звука: {e}") from e
    default_id = ""
    try:
        sp = AudioUtilities.GetSpeakers()
        default_id = str(getattr(sp, "id", None) or "")
    except Exception:  # noqa: BLE001, S110
        pass
    out = []
    for d in all_dev:
        # pycaw >= 2024 отдаёт объекты AudioDevice, старый — dict
        dev_id = str(getattr(d, "id", None) or (d.get("id") if isinstance(d, dict) else "") or "")
        name = str(getattr(d, "FriendlyName", None)
                   or (d.get("FriendlyName") if isinstance(d, dict) else "") or dev_id)
        # у render-устройств id начинается с «{0.0.0.…» (capture — «{0.0.1.…»)
        if not dev_id.startswith("{0.0.0."):
            continue
        out.append({"id": dev_id, "name": name, "is_default": dev_id == default_id})
    return out


def set_default_output(alias: str, aliases: dict | None = None) -> str:
    """Переключить устройство вывода по алиасу («наушники» -> имя устройства).
    aliases — словарь из конфига: алиас -> подстрока имени. Возвращает имя."""
    devices = list_output_devices()
    if not devices:
        raise ActionError("Не нашёл устройств звука")
    needle = (alias or "").strip().lower()
    for a, target in (aliases or {}).items():
        if str(a).lower() in needle or needle in str(a).lower():
            needle = str(target).lower()
            break
    match = next((d for d in devices if needle and needle in d["name"].lower()), None)
    if not match:
        names = ", ".join(d["name"] for d in devices)
        raise ActionError(f"Не нашёл устройство «{alias}». Есть: {names}")
    if match["is_default"]:
        return match["name"]
    import comtypes
    comtypes.CoInitialize()
    try:
        import comtypes.client
        ipc = comtypes.client.CreateObject(
            "{870af99c-171d-4f9e-af0d-e63df40c2bc9}", interface=_ipolicy_config())
        hr = ipc.SetDefaultEndpoint(match["id"], _ROLE_CONSOLE)
        if hr:
            raise ActionError(f"SetDefaultEndpoint вернул код {hr}")
    except ActionError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ActionError(f"не смог переключить звук: {e}") from e
    finally:
        comtypes.CoUninitialize()
    return match["name"]


def _audio_sessions():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetAllSessions()


def app_volume(app_query: str, percent: int | None = None,
               delta: int | None = None) -> tuple[str, int]:
    """Громкость приложения по имени процесса («chrome», «spotify»).
    percent — поставить, delta — изменить. Возвращает (имя_процесса, громкость)."""
    from pycaw.pycaw import AudioUtilities
    q = (app_query or "").strip().lower().replace(".exe", "")
    if not q:
        raise ActionError("Не указано приложение")
    hit = None
    for s in _audio_sessions():
        proc = getattr(s, "Process", None)
        try:
            name = (proc.name() if proc else "") or ""
        except Exception:  # noqa: BLE001, S110
            continue
        if q in name.lower().replace(".exe", ""):
            hit = (s, name)
            break
    if hit is None:
        raise ActionError(f"Не нашёл звуковой поток приложения «{app_query}» — "
                          f"запусти приложение и повтори")
    session, name = hit
    vol = getattr(session, "SimpleAudioVolume", None)
    if vol is None:
        raise ActionError(f"Не смог управлять громкостью «{name}»")
    cur = int(round(vol.GetMasterVolume() * 100))
    if percent is not None:
        new = max(0, min(100, int(percent)))
    elif delta is not None:
        new = max(0, min(100, cur + int(delta)))
    else:
        return name, cur
    vol.SetMasterVolume(new / 100.0, None)
    return name, new


# ============================================================================
#  Ввод текста в активное окно (задача 30): SendInput Unicode + буфер обмена
# ============================================================================

INPUT_UNICODE = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK, VK_CONTROL, VK_V, VK_C, VK_INSERT = 0x08, 0x11, 0x56, 0x43, 0x2D
VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN = 0x12, 0x10, 0x5B, 0x5C


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_uint), ("time", ctypes.c_uint),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                ("time", ctypes.c_uint),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint), ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint), ("union", _INPUTUNION)]


def send_text_unicode(text: str, delay_ms: int = 8) -> None:
    """Посимвольный ввод через SendInput KEYEVENTF_UNICODE:
    кириллица, эмодзи и знаки — без раскладки клавиатуры."""
    user32 = ctypes.windll.user32
    for ch in text:
        if ch == "\b":
            _send_vk(user32, VK_BACK)
            continue
        inp = _INPUT()
        inp.type = INPUT_UNICODE
        inp.union.ki = _KEYBDINPUT(0, ord(ch), KEYEVENTF_UNICODE, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if delay_ms:
            time.sleep(max(1, int(delay_ms)) / 1000.0)


def _send_vk(user32, vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def send_ctrl_v(paste_delay: float = 0.3) -> None:
    user32 = ctypes.windll.user32
    _send_vk(user32, VK_CONTROL)
    time.sleep(0.02)
    _send_vk(user32, VK_V)
    time.sleep(max(0.1, float(paste_delay)))


def send_backspace(count: int, delay_ms: int = 12) -> None:
    """Стереть count символов (для «удали последнее слово», «отмени ввод»)."""
    user32 = ctypes.windll.user32
    for _ in range(max(0, int(count))):
        _send_vk(user32, VK_BACK)
        if delay_ms:
            time.sleep(max(1, int(delay_ms)) / 1000.0)


# ----- буфер обмена -----------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _clipboard_open(user32, attempts: int = 10, delay: float = 0.05) -> bool:
    for _ in range(attempts):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def get_clipboard_text() -> str:
    """Прочитать CF_UNICODETEXT с повторами. ActionError содержит причину."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    if not _clipboard_open(user32):
        raise ActionError("нет доступа к буферу обмена: он занят другой программой")
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            raise ActionError("в буфере обмена нет текстового содержимого")
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            raise ActionError("не удалось прочитать текст из буфера обмена")
        p = kernel32.GlobalLock(h)
        if not p:
            raise ActionError("не удалось открыть текст в буфере обмена")
        try:
            raw = ctypes.string_at(p, kernel32.GlobalSize(h))
            text = raw.decode("utf-16-le").rstrip("\x00")
            if not text.strip():
                raise ActionError("в буфере обмена нет текста")
            return text
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_get_text() -> str | None:
    """Совместимый API: None при пустом/недоступном буфере."""
    try:
        return get_clipboard_text()
    except ActionError:
        return None


def clipboard_set_text(text: str) -> bool:
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    data = (text or "").encode("utf-16-le") + b"\x00\x00"
    if not _clipboard_open(user32):
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = kernel32.GlobalLock(h)
        if not p:
            kernel32.GlobalFree(h)
            return False
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, h))
    finally:
        user32.CloseClipboard()


def _release_modifiers(user32) -> None:
    for vk in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _send_shortcut(user32, key: int) -> None:
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(key, 0, 0, 0)
    user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def clipboard_selected_text() -> str:
    """Скопировать выделение Ctrl+C/Ctrl+Insert и восстановить прежний текстовый буфер."""
    old = clipboard_get_text()
    user32 = ctypes.windll.user32
    sequence = user32.GetClipboardSequenceNumber()
    _release_modifiers(user32)
    try:
        for key in (VK_C, VK_INSERT):
            _send_shortcut(user32, key)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if user32.GetClipboardSequenceNumber() != sequence:
                    return get_clipboard_text()
                time.sleep(0.025)
        raise ActionError("ничего не выделено или окно не даёт скопировать")
    finally:
        if old is not None and not clipboard_set_text(old):
            raise ActionError("прочитал выделенное, но не смог восстановить прежний буфер")


def paste_via_clipboard(text: str, restore: bool = True,
                        paste_delay: float = 0.3) -> None:
    """Сохранить буфер -> вставить текст Ctrl+V -> вернуть буфер."""
    old = clipboard_get_text() if restore else None
    if not clipboard_set_text(text):
        raise ActionError("буфер обмена занят — не смог вставить текст")
    time.sleep(0.05)
    send_ctrl_v(paste_delay)
    time.sleep(0.25)
    if restore:
        clipboard_set_text(old or "")


# ----- активное окно и безопасность ввода -------------------------------------

def active_window() -> dict:
    """{hwnd, title, process} активного окна."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {"hwnd": 0, "title": "", "process": ""}
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process = ""
    try:
        import psutil
        process = psutil.Process(pid.value).name()
    except Exception:  # noqa: BLE001, S110
        pass
    return {"hwnd": int(hwnd), "title": buf.value, "process": process}


# окна, куда вводить нельзя: экран блокировки, UAC, ввод пароля Windows
SAFE_BLOCK_TITLES = (
    "credential ui", "credui", "uac", "контроль учетных записей",
    "user account control", "windows security", "введите пароль",
    "введите пароль windows", "вход в систему",
)
SAFE_BLOCK_PROCS = ("logonui.exe", "consent.exe", "credui.exe", "authui.exe")


def input_block_reason(win: dict) -> str | None:
    """Причина, почему в это окно вводить нельзя (None — можно)."""
    proc = (win.get("process") or "").lower()
    title = (win.get("title") or "").lower()
    if proc in SAFE_BLOCK_PROCS:
        return "Это системное окно ввода пароля — вводить текст туда нельзя."
    for s in SAFE_BLOCK_TITLES:
        if s in title:
            return f"Окно «{win.get('title')}» похоже на окно пароля — не ввожу."
    return None


def window_is_elevated(hwnd: int) -> bool | None:
    """Окно запущено от администратора? None — проверить не удалось."""
    if not hwnd:
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    try:
        kernel32, advapi32 = ctypes.windll.kernel32, ctypes.windll.advapi32
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hproc:
            return None
        try:
            token = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(token)):
                return None
            try:
                elev = wintypes.DWORD()
                out = wintypes.DWORD()
                # TokenElevation = 20
                ok = advapi32.GetTokenInformation(token, 20, ctypes.byref(elev),
                                                  ctypes.sizeof(elev), ctypes.byref(out))
                return bool(elev.value) if ok else None
            finally:
                advapi32.CloseHandle(token)
        finally:
            kernel32.CloseHandle(hproc)
    except Exception:  # noqa: BLE001
        return None


def is_running_as_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


ELEVATED_HINT = ("не могу вводить в окно с повышенными правами — "
                 "запусти Джарвиса от администратора "
                 "(настройки, вкладка «Общие» → Планировщик)")


# ----- очередь ввода (не блокирует распознавание) -----------------------------

# терминалы: в них вставка идёт через буфер, SendInput часто теряет символы
TERMINAL_PROCS = frozenset({"cmd.exe", "powershell.exe", "pwsh.exe",
                            "windowsterminal.exe", "conhost.exe", "wt.exe"})

_type_queue: queue.Queue = queue.Queue()
_type_thread: threading.Thread | None = None
_type_lock = threading.Lock()


def _type_worker() -> None:
    while True:
        item = _type_queue.get()
        if item is None:
            return
        text, method, delay_ms, callback = item
        try:
            if method == "clipboard":
                paste_via_clipboard(text)
            elif method == "unicode":
                send_text_unicode(text, delay_ms)
            else:  # auto: длинный текст (>200) или терминал — буфер, иначе Unicode
                proc = (active_window().get("process") or "").lower()
                if len(text) > 200 or proc in TERMINAL_PROCS:
                    paste_via_clipboard(text)
                else:
                    send_text_unicode(text, delay_ms)
            if callback:
                callback(None)
        except Exception as e:  # noqa: BLE001
            if callback:
                callback(e)


def start_type_worker() -> None:
    global _type_thread
    with _type_lock:
        if _type_thread is None or not _type_thread.is_alive():
            _type_thread = threading.Thread(target=_type_worker, daemon=True,
                                            name="jarvis-type")
            _type_thread.start()


def type_text(text: str, method: str = "auto", delay_ms: int = 8,
              callback=None) -> None:
    """Поставить текст в очередь ввода (отдельный поток, распознавание не ждёт).
    method: auto | unicode | clipboard. callback(err) — по завершении."""
    if not text:
        if callback:
            callback(None)
        return
    start_type_worker()
    _type_queue.put((text, method, int(delay_ms), callback))


def type_text_sync(text: str, method: str = "auto", delay_ms: int = 8) -> None:
    """Ввод синхронно (для команд, которые сразу отвечают результатом)."""
    if not text:
        return
    if method == "clipboard":
        paste_via_clipboard(text)
    elif method == "unicode":
        send_text_unicode(text, delay_ms)
    else:
        proc = (active_window().get("process") or "").lower()
        if len(text) > 200 or proc in TERMINAL_PROCS:
            paste_via_clipboard(text)
        else:
            send_text_unicode(text, delay_ms)


# ============================================================================
#  Глобальная горячая клавиша (задача 50): RegisterHotKey в отдельном потоке
# ============================================================================

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """«ctrl+alt+j» -> (модификаторы, виртуальный код клавиши). None — криво."""
    spec = (spec or "").strip().lower()
    if not spec:
        return None
    parts = [p.strip() for p in spec.replace("-", "+").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key = ""
    for p in parts:
        if p in ("ctrl", "control", "контрол"):
            mods |= MOD_CONTROL
        elif p in ("alt", "меню", "альт"):
            mods |= MOD_ALT
        elif p in ("shift", "шифт"):
            mods |= MOD_SHIFT
        elif p in ("win", "windows", "winkey"):
            mods |= MOD_WIN
        else:
            key = p
    if not key:
        return None
    if len(key) == 1 and key.isascii():
        vk = ord(key.upper())
    else:
        vk = {"esc": 0x1B, "escape": 0x1B, "space": 0x20, "pause": 0x13,
              "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
              "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
              "f11": 0x7A, "f12": 0x7B}.get(key, 0)
    if not vk:
        return None
    return mods | MOD_NOREPEAT, vk


class HotkeyListener:
    """Слушает RegisterHotKey в отдельном потоке; при нажатии зовёт on_press().
    При конфликте on_error получит текст причины."""

    def __init__(self, on_press, on_error=None):
        self.on_press = on_press
        self.on_error = on_error
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._spec = ""

    @property
    def spec(self) -> str:
        return self._spec

    def start(self, spec: str) -> bool:
        """(пере)запустить слушатель для «ctrl+alt+j». False — конфликт/криво."""
        self.stop(wait=1.0)
        parsed = parse_hotkey(spec)
        if parsed is None:
            if self.on_error:
                self.on_error(f"не поняла горячую клавишу «{spec}» — нужна вроде ctrl+alt+j")
            return False
        self._spec = spec
        self._stop.clear()
        mods, vk = parsed
        failed: list = []

        def run():
            user32 = ctypes.windll.user32
            HOTKEY_ID = 0xBEEF
            if not user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
                failed.append(f"горячая клавиша «{spec}» занята другой программой")
                return
            try:
                msg = wintypes.MSG()
                while not self._stop.is_set():
                    r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if r <= 0:
                        break
                    if r == -1:
                        break
                    if msg.message == 0x0312:  # WM_HOTKEY
                        try:
                            self.on_press()
                        except Exception:  # noqa: BLE001
                            pass
            finally:
                user32.UnregisterHotKey(None, HOTKEY_ID)

        self._thread = threading.Thread(target=run, daemon=True, name="jarvis-hotkey")
        self._thread.start()
        time.sleep(0.3)  # RegisterHotKey успевает отработать
        if failed:
            if self.on_error:
                self.on_error(failed[0])
            return False
        return True

    def stop(self, wait: float = 0.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            try:  # будим GetMessage, чтобы поток завершился
                ctypes.windll.user32.PostThreadMessageW(self._thread.ident or 0,
                                                        0x0012, 0, 0)  # WM_QUIT
            except Exception:  # noqa: BLE001
                pass
            if wait:
                self._thread.join(timeout=wait)
