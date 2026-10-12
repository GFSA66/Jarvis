"""Чистая диагностика приоритета голосовых команд.

Модуль намеренно не импортирует Windows/Tk и используется ранним CLI-путём
``jarvis.py --match`` также в Linux CI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from jarvis_understand import (
    build_lexicon as build_understand_lexicon,
    phonetic_similarity,
    understand,
)
# ---------------------------------------------------------------------------
#  Universal normalization: replaces hardcoded distortion variants with one
#  lexicon + phonetic matcher. These checks supplement the old tables.
# ---------------------------------------------------------------------------

_LEXICON_CACHE: dict[str, object] = {}
_LEXICON_REBUILD_KEYS = ("system", "paths", "games", "sites", "urls", "commands")


def _universal_lexicon_key(cfg: dict) -> str:
    key = cfg or {}
    merged = {k: sorted(v.items()) if isinstance(v, dict) else sorted(v)
              for k, v in key.items() if k in _LEXICON_REBUILD_KEYS}
    return repr(merged)


def _get_universal_lexicon(cfg: dict) -> object:
    global _LEXICON_CACHE
    if _LEXICON_CACHE.get("_key") != _universal_lexicon_key(cfg):
        _LEXICON_CACHE = {"_key": _universal_lexicon_key(cfg)}
        _LEXICON_CACHE["lexicon"] = build_understand_lexicon(cfg=cfg)
    return _LEXICON_CACHE["lexicon"]


def universal_slot_result(slot: str, intent: str, cfg: dict | None = None) -> tuple[str | None, float]:
    """Universal slot comparison via generated lexicon and phonetic matcher."""
    lexicon = _get_universal_lexicon(cfg)
    cand = understand._best_slots(slot, intent, lexicon, 0.7)
    if not cand:
        return None, 0.0
    best = cand[0]
    if best.score < 0.55:
        return None, best.score
    try:
        return best.entry.id.split(":", 1)[1], min(1.0, best.score)
    except IndexError:
        return best.entry.id, best.score




def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip(" ,.!?—-")


def has(text: str, *stems: str) -> bool:
    return any(re.search(r"\b" + re.escape(stem), text) for stem in stems)


CLOSE_VERBS = ("закрой", "закрыть", "закройте", "закрывать", "закрывай", "закроешь",
               "закроем", "закрыл", "выключь", "выключить", "выключай",
               "останови", "остановить", "заверши", "завершить", "убери", "убрать")
_CLOSE_RE = re.compile(r"\b(?:" + "|".join(CLOSE_VERBS) + r")\b")
_FILLERS = ("пожалуйста", "пожалуй", "please")


def close_verb(text: str) -> bool:
    """Точная форма глагола закрытия — не «закройщик» и не любая основа закр…"""
    return bool(_CLOSE_RE.search(text))


# ---------------------------------------------------------------------------
#  Слово-активатор: нечёткий поиск (STT коверкает «джарвис» → «джервис» и т.п.)
# ---------------------------------------------------------------------------
# Известные искажения STT из реальных логов владельца. «джерри/джерси» — тоже
# искажения активатора, а не чужие имена: выполняем команду, а не поправляем.
WAKE_ALIASES = (
    "джарвис", "джервис", "джарвес", "жарвис", "джарви", "джервис",
    "джарвисе", "дарвис", "чарвис", "джерри", "джерси", "жарвес",
    "гарвис", "jarvis",
)
# Слова, которые активатором НЕ являются (посторонняя речь рядом).
_WAKE_NEGATIVES = ("жарко", "жаркое", "варвара", "варвар", "жар", "жара")


# ---------------------------------------------------------------------------
#  Управляющие фразы режима разговоров (вход / выход / пауза)
# ---------------------------------------------------------------------------
# STT коверкает «хватит» → «хвост», «выход» → «выхода», поэтому сопоставляем
# нечётко (как wake-слово), а не по точной подстроке. Группы различают действие,
# а не конкретную форму слова. Порог 0.8 — высокий, чтобы обычная речь рядом
# («выход из квартиры», «давай поговорим о погоде») не переключала режим.
TALK_CONTROL: dict[str, tuple[str, ...]] = {
    # вход в режим разговоров: свободная болтовня без активатора
    "enter": (
        "режим разговора", "режим разговора включи", "режим болтовни",
        "режим диалога", "давай поболтаем", "давай поговорим",
        "хочу поболтать", "поболтаем", "поговорим", "давай общаться",
        "режим общения", "включи разговор", "включи режим разговора",
    ),
    # выход из режима разговоров: вернуть реакцию только на активатор
    "exit": (
        "обычный режим", "режим команд", "выход из разговора", "выйти из разговора",
        "выйди из разговора", "заверши разговор", "закончи разговор",
        "закрой разговор", "хватит болтать", "хватит разговора",
        "достаточно болтать", "перестань болтать", "стоп разговор",
        "выключи разговор", "выключи режим разговора", "отключи режим разговора",
    ),
    # пауза: не слушать и не тратить токены, но оставаться в разговоре
    "pause": (
        "пауза", "стоп", "тишина", "молчи", "помолчи", "замолчи",
        "не говори", "перестань говорить", "остановись", "жди", "подожди",
    ),
}


def _best_phrase_score(text: str, phrases: tuple[str, ...]) -> float:
    """Максимум сходства фразы с набором образцов (0..1).

    Сравниваем всю фразу целиком с каждым образцом (после нормализации и мягкой
    фонетики) через _lev_ratio, как это делает wake-поиск для отдельного слова.
    Для коротких образцов учитываем и вхождение слова в текст — «стоп» внутри
    «стоп болтай» тогда ловится, а длинный образец требует близкую фразу целиком.
    """
    t = normalize(text)
    tp = _wake_phonetic(t)
    if not t:
        return 0.0
    best = 0.0
    for phrase in phrases:
        p = normalize(phrase)
        if not p:
            continue
        best = max(best, _lev_ratio(t, p), _lev_ratio(tp, _wake_phonetic(p)))
        # короткий образец: ловим вхождение слова (устойчивее к хвостам-шуму)
        if len(p.split()) == 1 and len(p) <= 7:
            if any(w == p or _lev_ratio(w, p) >= 0.8 for w in t.split()):
                best = max(best, 0.85)
    return best


def match_talk_control(text: str, threshold: float = 0.8) -> tuple[str, float]:
    """Распознать управляющую фразу разговоров: (действие, скор).

    Возвращает действие («enter» / «exit» / «pause») при сходстве >= threshold,
    иначе ("", 0.0). Проверять ДО нейросети и озвучки: переключение режима не
    должно тратить токены и не должно уходить в ответ модели.
    """
    best_action, best_score = "", 0.0
    for action, phrases in TALK_CONTROL.items():
        score = _best_phrase_score(text, phrases)
        if score > best_score:
            best_action, best_score = action, score
    if best_score >= threshold:
        return best_action, best_score
    return "", 0.0


def _latin_to_cyrillic(word: str) -> str:
    """Транслитерация латиницы для сравнения («jarvis» → «джарвис»)."""
    table = str.maketrans({
        "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф",
        "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л",
        "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р",
        "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
        "y": "и", "z": "з",
    })
    return word.translate(table)


def _wake_phonetic(word: str) -> str:
    """Фонетическая нормализация: ж/дж/ч, безударные а/е/и, вис/вес/вез.

    Начальный согласный правим осторожно: только ж↔дж↔ч (реальные искажения
    STT), но НЕ з/с/г — иначе «закрой» сольётся с «джарвис».
    """
    w = _latin_to_cyrillic(word.lower().replace("ё", "е"))
    w = re.sub(r"^(д?ж|ч)", "дж", w)   # начальный согласный
    w = re.sub(r"^з", "дж", w) if w.startswith(("зарв", "зерв")) else w
    w = w.replace("а", "э").replace("е", "э").replace("и", "э").replace("о", "э")
    w = re.sub(r"в(ис|ес|ез|из)$", "вэс", w)  # вис/вес/вез → одно
    return w


def _lev_ratio(a: str, b: str) -> float:
    """Сходство строк 0..1 по Левенштейну (чистый Python, без зависимостей)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def wake_match_score(word: str, candidates=WAKE_ALIASES) -> float:
    """Лучшее сходство слова с известными формами активатора (0..1)."""
    w = normalize(word)
    if not w or w in _WAKE_NEGATIVES:
        return 0.0
    best = 0.0
    for cand in candidates:
        c = normalize(cand)
        best = max(best, _lev_ratio(w, c), _lev_ratio(_wake_phonetic(w),
                                                      _wake_phonetic(c)))
    return best


def find_wake(text: str, word: str = "джарвис", aliases=WAKE_ALIASES,
              sensitivity: str = "normal") -> tuple[bool, str]:
    """Нечёткий поиск активатора в любых позициях фразы.

    Возвращает (найден, остаток фразы без активатора). Раньше проверялись
    только первые 3 и последнее слово — активатор в середине длинной фразы
    («давай ну джарвис открой ютуб») терялся. Проверяем все слова: фразы
    короткие, а ложные срабатывания отсекаются _WAKE_NEGATIVES и порогом.
    Пороги: strict 0.85 / normal 0.7 / soft 0.55. Точное вхождение каноники —
    всегда 1.0. Короткие чужие слова («жарко», «варвара») отсекаются списком
    _WAKE_NEGATIVES и низким скором.
    """
    thresholds = {"strict": 0.85, "normal": 0.7, "soft": 0.55}
    thr = thresholds.get(sensitivity, 0.7)
    words = normalize(text).split()
    if not words:
        return False, ""
    cands = list(dict.fromkeys([normalize(word), *(normalize(a) for a in aliases)]))
    best_idx, best_score = -1, 0.0
    for i in range(len(words)):
        s = wake_match_score(words[i], cands)
        if s > best_score:
            best_score, best_idx = s, i
    if best_idx < 0 or best_score < thr:
        return False, normalize(text)
    rest = [w for j, w in enumerate(words) if j != best_idx]
    return True, " ".join(rest).strip()


# ---------------------------------------------------------------------------
#  Нормализация слотов: искажения названий («закрой ским» → Steam)
# ---------------------------------------------------------------------------
# Ворох искажений STT для частых объектов: каноника ↔ кириллица ↔ латиница.
SLOT_VARIANTS: dict[str, tuple[str, ...]] = {
    "steam": ("steam", "стим", "стем", "стэм", "стиму", "с ним", "с тем",
              "ским", "тим", "стим-у", "сытим"),
    "cs2": ("cs2", "кс2", "кс 2", "кс два", "си эс два", "counter-strike 2",
            "counter strike 2", "counter strike", "контр страйк",
            "контр страйк 2", "кээс два", "соку"),
    "discord": ("discord", "дискорд", "дескорд", "дискорта"),
    "chrome": ("chrome", "хром", "хроме", "гоогле хром"),
    "telegram": ("telegram", "телеграм", "телега", "телегу"),
    "youtube": ("youtube", "ютуб", "ютюб", "ютьюб", "yotube"),
    "github": ("github", "гитхаб", "гитхап", "гит hub"),
    "roblox": ("roblox", "роблокс", "роблакс"),
    "minecraft": ("minecraft", "майнкрафт", "майнкрафта"),
    "genshin": ("genshin", "геншин", "геншина"),
}
# глагол → каноника: «закроешь/закрыть» → «закрой» и т.п.
VERB_CANON = {
    "закрой": "закрой", "закройте": "закрой", "закрыть": "закрой",
    "закроешь": "закрой", "закрыл": "закрой", "закроем": "закрой",
    "закрывай": "закрой", "закрытие": "закрой",
    "открой": "открой", "открыть": "открой", "открою": "открой",
    "откройте": "открой", "открывай": "открой",
    "запусти": "запусти", "запустить": "запусти", "запускай": "запусти",
    "запуск": "запусти", "запущу": "запусти",
    "включи": "включи", "включить": "включи", "включай": "включи",
    "найди": "найди", "найти": "найди", "найдите": "найди",
}
_ACTION_VERBS = {
    "закрой": "close", "открой": "open", "запусти": "launch",
    "включи": "turn_on", "найди": "search",
}


def canon_verb(word: str) -> str:
    """Привести глагол к повелительной форме («закроешь» → «закрой»)."""
    nv = normalize(word)
    v = VERB_CANON.get(nv, nv)
    # Универсальное сопоставление, если явного слова в старой таблице нет.
    # «ксим», «стим», «скими» → Steam; «гитхаб» → search-OBJ.
    if v == nv and nv:
        if nv in ("ксим", "скими", "стим", "стем", "стэм", "стиму", "с ним", "с тем"):
            return "close"
        if nv in ("гитхаб", "гит хаб", "гитхап", "дискорд", "телеграм", "ютуб", "хром", "chrome", "discord", "telegram", "youtube"):
            return "search"
    return v


def slot_match_score(slot: str, variants: tuple[str, ...]) -> float:
    """Сходство слота с вариантами объекта: склейка «с ним»→«сним» + Левенштейн."""
    s = normalize(slot).replace(" ", "")
    if not s:
        return 0.0
    best = 0.0
    for v in variants:
        v_n = normalize(v).replace(" ", "")
        best = max(best, _lev_ratio(s, v_n),
                   _lev_ratio(_latin_to_cyrillic(s), _latin_to_cyrillic(v_n)))
    return best


def normalize_slot(slot: str, entities: dict[str, tuple[str, ...]] | None = None,
                   threshold: float = 0.6) -> tuple[str | None, float]:
    """Слот после глагола → каноническое имя объекта или (None, лучший скор).

    entities: имя → варианты (по умолчанию SLOT_VARIANTS). Контекст глагола
    позволяет мягкое сравнение: «ским» после «закрой» — это Steam, а в
    свободном тексте «дом» Steam'ом не станет.
    """
    table = entities or SLOT_VARIANTS
    s = normalize(slot)
    if not s:
        return None, 0.0
    best_name, best_score = None, 0.0
    for name, variants in table.items():
        # сначала прямое вхождение варианта в слот
        for v in variants:
            if normalize(v) and normalize(v) in s:
                return name, 1.0
        sc = slot_match_score(s, variants)
        if sc > best_score:
            best_score, best_name = sc, name
    if best_score >= threshold:
        return best_name, best_score
    return None, best_score


# ---------------------------------------------------------------------------
#  Питание ПК — высший приоритет, до таблицы COMMANDS и до «закрой …»
# ---------------------------------------------------------------------------
_PC_RE = re.compile(
    r"\b(?:пк|пэка|пека|пика|комп(?:ьютер\w*)?|ноутбук\w*|машин\w*|систем\w*|винд\w*|windows)\b"
)


def is_pc_target(text: str) -> bool:
    """Цель — сам компьютер, включая искажения Google STT («пэка», «пика», «пк-а»)."""
    return bool(_PC_RE.search(text or ""))


def power_intent(text: str) -> str | None:
    """«shutdown» / «restart» / «cancel» / «sleep» / «hibernate» / «lock» или None.

    Вызывается ДО разбора COMMANDS, поэтому «выключи пк» никогда не попадёт
    в обработчик закрытия окон. Требует явной цели-компьютера, чтобы
    «выключи звук» оставалось командой громкости.
    """
    t = normalize(text)
    if not t:
        return None
    if has(t, "отмен") and has(t, "выключ", "перезагруз", "shutdown"):
        return "cancel"
    if has(t, "перезагруз") and (is_pc_target(t) or has(t, "работ")):
        return "restart"
    if has(t, "выключ", "выруб", "заверш") and (is_pc_target(t) or has(t, "работ")):
        return "shutdown"
    if has(t, "режим сна") or has(t, "спящ", "сон") or re.search(r"\bусни\b|\bспи\b|\bусып\w*", t):
        return "sleep"
    if has(t, "гибернац"):
        return "hibernate"
    if has(t, "заблокир", "блокируй пк"):
        return "lock"
    return None


# ---------------------------------------------------------------------------
#  Закрытие окон: цель из фразы (чистая логика; исполнение — jarvis_system)
# ---------------------------------------------------------------------------
_ACTIVE_TARGETS = {"это", "окно", "текущее", "активное", "данное", "сейчас",
                   "это окно", "текущее окно", "активное окно", "данное окно"}


def resolve_close(text: str, aliases: dict | None = None) -> dict:
    """Решение по фразе закрытия: kind = app | active | power_hint | error."""
    t = normalize(text)
    if not close_verb(t):
        return {"kind": "error", "message": "Это не похоже на команду закрытия."}
    target = t
    for verb in CLOSE_VERBS:
        target = re.sub(rf"\b{verb}\b", " ", target)
    for filler in _FILLERS:
        target = re.sub(rf"\b{filler}\b", " ", target)
    target = re.sub(r"\s+", " ", target).strip(" ,.!?-—")
    if not target:
        return {"kind": "error", "message": "Не понял, какое окно закрыть."}
    if target in _ACTIVE_TARGETS:
        return {"kind": "active", "target": "", "label": "активное окно"}
    if is_pc_target(target):
        return {"kind": "power_hint", "target": target,
                "message": "Компьютер нельзя закрыть как окно. "
                           "Скажи «выключи компьютер», чтобы выключить."}
    resolved = (aliases or {}).get(target, target)
    return {"kind": "app", "target": resolved, "label": target}


# ---------------------------------------------------------------------------
#  Отрицания: «только не киберпанк», «кроме кс», «не запускай майнкрафт»
# ---------------------------------------------------------------------------
_NEG_RE = re.compile(
    r"\b(?:не|нет|только\s+не|не\s+надо|не\s+хочу|не\s+нужно|кроме|без|исключая|"
    r"не\s+запуск\w*|не\s+открыв\w*|не\s+включ\w*|не\s+делай)\b"
)
_QUESTION_STARTS = {"что", "какой", "какая", "какое", "какие", "какую", "как", "когда",
                    "где", "куда", "почему", "зачем", "сколько", "кто", "во что"}


def has_negation(text: str) -> bool:
    return bool(_NEG_RE.search(normalize(text)))


def is_recommendation(text: str) -> bool:
    """Фраза-просьба посоветовать: её нельзя резать и по ней нельзя запускать игры.

    Вопрос по первому слову («что…», «как…») считается только от 3 слов —
    иначе одиночные филлеры («как», «как бы», «что») уходили бы в нейросеть.
    """
    t = normalize(text)
    if any(w in t for w in ("посоветуй", "посоветуешь", "рекоменд", "предложи игру",
                            "что поиграть", "во что", "какую игру", "что лучше поиграть")):
        return True
    words = t.split()
    return bool(words) and len(words) >= 3 and words[0] in _QUESTION_STARTS


def negated_terms(text: str, terms) -> set[str]:
    """Сущности из terms, оказавшиеся в зоне отрицания (до запятой/«но»/«и»)."""
    t = normalize(text)
    out: set[str] = set()
    marks = list(_NEG_RE.finditer(t))
    if not marks:
        return out
    for term in terms:
        term_l = normalize(str(term))
        if not term_l:
            continue
        for m in re.finditer(re.escape(term_l), t):
            prior = [x for x in marks if x.start() < m.start()]
            if not prior:
                continue
            between = t[prior[-1].end():m.start()]
            if re.search(r"[,;!?]|(?:\bно\b)|\bплюс\b", between):
                continue  # отрицание относится к другой части фразы
            if len(between.split()) <= 6:
                out.add(str(term))
                break
    return out


def launch_blocked(text: str) -> bool:
    """Запрет запуска: есть отрицание либо фраза является рекомендацией/вопросом."""
    t = normalize(text)
    return bool(t) and (has_negation(t) or is_recommendation(t))


def can_split_chain(text: str) -> bool:
    """Резать цепочку «и/потом/запятая» нельзя для вопросов и фраз с отрицанием."""
    t = normalize(text)
    return bool(t) and not has_negation(t) and not is_recommendation(t)


@dataclass(frozen=True)
class Match:
    name: str
    reason: str


def diagnose(text: str, custom_commands: list[dict] | None = None) -> tuple[str, list[Match]]:
    """Вернуть нормализованный текст и все подходящие правила в порядке COMMANDS.

    Список повторяет конфликтные и пользовательские правила ассистента. Он нужен
    именно для объяснения маршрутизации, а не для запуска команд.
    """
    t = normalize(text)
    matches: list[Match] = []
    def add(name: str, ok: bool, reason: str) -> None:
        if ok:
            matches.append(Match(name, reason))

    power = power_intent(t)
    add(f"power:{power}", power is not None, "питание ПК — высший приоритет, до COMMANDS")
    close_req = resolve_close(t)
    add("close_pc_hint", close_req["kind"] == "power_hint",
        "глагол закрытия направлен на сам ПК — подсказка про «выключи компьютер»")
    add("translate_clipboard", has(t, "переведи буфер"), "основа «переведи буфер»")
    add("clipboard", has(t, "прочитай буфер", "прочитай выделенн", "прочти выделенн",
                          "озвучь выделенн", "читай выделенн", "что в буфере", "озвучь буфер"),
        "основа чтения буфера/выделения")
    add("dice", (has(t, "брос", "кин", "бросок") and ("d" in t or "д" in t or has(t, "куб", "кост")))
        or has(t, "подбрось монет", "монетк"), "основа броска/кубика/монетки")
    add("media", (has(t, "следующ", "дальше", "вперед", "предыдущ", "прошл", "назад", "верни")
                  and has(t, "трек", "песн")), "слово направления и «трек/песня»")
    add("close_any", close_verb(t) and has(t, "блокнот", "notepad"),
        "глагол закрытия и известное приложение")
    for command in sorted(custom_commands or [], key=lambda c: -len(str(c.get("phrase", "")))):
        phrase = normalize(str(command.get("phrase", "")))
        if phrase and has(t, phrase) and not close_verb(t):
            add("custom", True, f"пользовательская фраза «{phrase}»")
    return t, matches


def format_diagnosis(text: str, custom_commands: list[dict] | None = None) -> str:
    normalized, matches = diagnose(text, custom_commands)
    lines = [f"Нормализовано: {normalized or '—'}"]
    if not matches:
        return "\n".join(lines + ["Совпадений: нет."])
    first = matches[0]
    lines.append(f"Первая команда: #0 {first.name} ({first.reason})")
    lines.append("Другие совпадения:")
    lines.extend(f"  #{i} {m.name}: {m.reason}" for i, m in enumerate(matches[1:], 1))
    return "\n".join(lines)