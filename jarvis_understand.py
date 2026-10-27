"""Единый локальный слой понимания голосовых команд.

Модуль намеренно чистый: он не импортирует Windows, Tk, STT-бэкенды или
``jarvis.py``. Аудио даёт список гипотез, приложение даёт снимок известных
объектов, а на выходе получается проверяемое решение ``Decision``.

Это не «исправление Steam»: лексикон строится из конфигурации и контекста,
поэтому новая игра, ссылка, пользовательская команда или алиас попадают в ту
же схему без правки алгоритма.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


def normalize(text: str) -> str:
    """Нормальная форма для сравнения, без пунктуации и лишних пробелов."""
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")
                  .replace("ъ", "").replace("ь", "")).strip(" ,.!?;:—-_")


def words(text: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+", normalize(text))


_LATIN_CHUNKS = (
    ("sch", "щ"), ("shch", "щ"), ("zh", "ж"), ("ch", "ч"), ("sh", "ш"),
    ("ya", "я"), ("yu", "ю"), ("yo", "е"), ("kh", "х"), ("ts", "ц"),
    ("th", "т"), ("ph", "ф"),
)
_LATIN_SINGLE = str.maketrans({
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "и", "z": "з",
})
_CYR_TO_LATIN = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ы": "y",
    "э": "e", "ю": "yu", "я": "ya",
})


def latin_to_cyrillic(text: str) -> str:
    # Устойчивая англоязычная схема произносимого написания. Жёстко не привязываем
    # к конкретным брендам: правила должны масштабироваться на новые приложения.
    out = normalize(text)
    # ea в заимствованиях обычно читается как /e/ или /i/ (Steam, Team, Play).
    out = re.sub(r"ea", "i", out)
    # ch перед r/l часто читается как /к/ в греческих/технических словах
    # (chrome, architecture); в остальных позициях остаётся /ч/.
    out = re.sub(r"ch(?=[rl])", "k", out)
    for src, dst in _LATIN_CHUNKS:
        out = out.replace(src, dst)
    return out.translate(_LATIN_SINGLE)


def cyrillic_to_latin(text: str) -> str:
    return normalize(text).translate(_CYR_TO_LATIN)


_DIGITS_RU = {
    "0": ("ноль",), "1": ("один", "раз"), "2": ("два",), "3": ("три",),
    "4": ("четыре",), "5": ("пять",), "6": ("шесть",), "7": ("семь",),
    "8": ("восемь",), "9": ("девять",),
}
_LETTER_RU = {"c": "с", "s": "эс", "v": "в", "l": "эл", "g": "джи", "t": "ти",
              "y": "у", "x": "икс", "b": "би", "p": "пи", "d": "ди", "k": "кей"}


def spoken_forms(name: str) -> set[str]:
    """Автоматические произносимые формы названия, без базы исключений объектов."""
    raw = re.sub(r"([a-zа-я])([A-ZА-Я])", r"\1 \2", str(name or ""))
    raw = re.sub(r"([a-zA-Zа-яА-Я])(\d)", r"\1 \2", raw)
    raw = re.sub(r"(\d)([a-zA-Zа-яА-Я])", r"\1 \2", raw)
    base = normalize(raw)
    if not base:
        return set()
    out = {base, base.replace("-", " "), base.replace("-", "")}
    if re.search(r"[a-z]", base):
        cyr = latin_to_cyrillic(base)
        out.add(cyr)
        # Плюс вариант с пробелами, удобный для произносимых цепочек.
        out.add(cyr.replace("-", " "))
        # Буквенное чтение коротких латинских аббревиатур: VLC -> «вэлси».
        compact = "".join(words(base))
        if 2 <= len(compact) <= 5 and compact.isalpha():
            out.add(" ".join(_LETTER_RU.get(ch, ch) for ch in compact))
            out.add("".join(_LETTER_RU.get(ch, ch) for ch in compact))
    if re.search(r"[а-я]", base):
        out.add(cyrillic_to_latin(base))
    for form in tuple(out):
        expanded = []
        for token in words(form):
            expanded.append(token)
            if token.isdigit():
                expanded.extend(_DIGITS_RU.get(token, (token,)))
            else:
                m = re.fullmatch(r"([a-zа-я]+)(\d+)", token)
                if m:
                    expanded.append(m.group(1) + " " + " ".join(
                        x for d in m.group(2) for x in _DIGITS_RU.get(d, (d,))))
        out.update(expanded)
    toks = words(base)
    if len(toks) >= 2:
        out.add("".join(t[0] for t in toks if t))
        out.add(" ".join(toks[:2]))
        out.add(toks[0])
    return {normalize(x) for x in out if normalize(x)}


def phonetic_key(text: str) -> str:
    """Русский фонетический ключ: устойчив к раскладке, редукциям и оглушению."""
    s = latin_to_cyrillic(text) if re.search(r"[a-z]", normalize(text)) else normalize(text)
    s = re.sub(r"[^а-я0-9]", "", s)
    # Частые эквивалентные группы/сочетания сначала, затем гласные и согласные.
    s = (s.replace("ться", "ца").replace("тся", "ца").replace("тс", "ц")
           .replace("дс", "ц").replace("сч", "щ").replace("щ", "ш")
           .replace("й", "и").replace("ы", "и").replace("я", "е").replace("ю", "у"))
    # В быстрой речи граница «с ним» часто склеивается, а носовой в такой
    # позиции распознаётся как взрывной: сним/стим. Это правило фонетической
    # позиции, а не исключение конкретного имени.
    s = re.sub(r"([сз])н(?=[еиаоу]?[м])", r"\1т", s)
    s = re.sub(r"[ао]", "а", s)
    s = re.sub(r"[еиэ]", "е", s)
    s = re.sub(r"[бп]", "п", s)
    s = re.sub(r"[вф]", "ф", s)
    s = re.sub(r"[гкх]", "к", s)
    s = re.sub(r"[дт]", "т", s)
    s = re.sub(r"[зс]", "с", s)
    s = re.sub(r"[жшч]", "ш", s)
    return re.sub(r"(.)\1+", r"\1", s)


def _weighted_similarity(a: str, b: str) -> float:
    a, b = phonetic_key(a), phonetic_key(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    groups = (set("пб"), set("фв"), set("ктгх"), set("тд"), set("сз"), set("шжч"),
              set("ае"), set("ау"), set("еи"))
    prev = [float(i) for i in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        for j, cb in enumerate(b, 1):
            sub = 0.0 if ca == cb else (0.35 if any(ca in g and cb in g for g in groups) else 1.0)
            cur.append(min(prev[j] + 1.0, cur[-1] + 1.0, prev[j - 1] + sub))
        prev = cur
    return max(0.0, 1.0 - prev[-1] / max(len(a), len(b)))


def _ngrams(text: str, n: int = 2) -> set[str]:
    text = phonetic_key(text)
    return {text[i:i + n] for i in range(max(0, len(text) - n + 1))} or {text}


def phonetic_similarity(a: str, b: str) -> float:
    """Комбинация взвешенного Левенштейна, n-грамм и близости слогов."""
    lev = _weighted_similarity(a, b)
    aa, bb = _ngrams(a), _ngrams(b)
    gram = len(aa & bb) / max(1, len(aa | bb))
    syll_a = max(1, len(re.findall(r"[аеёиоуыэюя]", latin_to_cyrillic(a))))
    syll_b = max(1, len(re.findall(r"[аеёиоуыэюя]", latin_to_cyrillic(b))))
    syll = max(0.0, 1.0 - abs(syll_a - syll_b) / max(syll_a, syll_b))
    return 0.62 * lev + 0.28 * gram + 0.10 * syll


@dataclass(frozen=True)
class Hypothesis:
    text: str
    confidence: float = 0.7
    engine: str = "unknown"


@dataclass(frozen=True)
class LexiconEntry:
    id: str
    label: str
    kind: str
    aliases: tuple[str, ...]
    actions: frozenset[str]
    priority: float = 0.0


@dataclass
class Lexicon:
    entries: list[LexiconEntry] = field(default_factory=list)
    verbs: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def grammar_words(self) -> list[str]:
        out = []
        for forms in self.verbs.values():
            out.extend(forms)
        for entry in self.entries:
            out.extend(entry.aliases)
        return sorted({w for form in out for w in words(form) if len(w) >= 2})


DEFAULT_VERBS: dict[str, tuple[str, ...]] = {
    "open": ("открой", "открыть", "откройте", "открывай", "покажи"),
    "launch": ("запусти", "запустить", "запускай", "стартуй", "включи", "включить"),
    "close": ("закрой", "закрыть", "закроешь", "закройте", "закрывай", "заверши", "останови", "выруби"),
    "search": ("найди", "найти", "загугли", "поищи"),
    "volume_up": ("громче", "погромче", "прибавь"),
    "volume_down": ("тише", "потише", "убавь"),
    "media": ("пауза", "стоп", "дальше", "назад", "следующий", "предыдущий"),
}
_ACTION_KINDS = {
    "close": frozenset({"app", "game", "window"}),
    "open": frozenset({"app", "site", "folder", "command", "game", "file"}),
    "launch": frozenset({"app", "game", "command"}),
    "search": frozenset({"site", "folder", "command"}),
}
_RISK = {"close": "medium", "launch": "medium", "open": "safe", "search": "safe",
         "volume_up": "safe", "volume_down": "safe", "media": "safe"}


def _pronunciations(cfg: dict) -> dict[str, tuple[str, int]]:
    out = {}
    raw = cfg.get("pronunciations") or {}
    if not isinstance(raw, dict):
        return out
    for heard, value in raw.items():
        if isinstance(value, str):
            out[normalize(heard)] = (value, 1)
        elif isinstance(value, dict) and value.get("target"):
            out[normalize(heard)] = (str(value["target"]), int(value.get("count") or 1))
    return out


def build_lexicon(cfg: dict | None = None, context: dict | None = None) -> Lexicon:
    """Собрать единственный словарь из конфига и динамического снимка системы.

    ``context`` опционально: ``running``, ``windows``, ``folders`` и ``recent``
    можно передавать на каждом запросе без сохранения машинных данных в конфиг.
    """
    cfg, context = cfg or {}, context or {}
    entries: dict[str, LexiconEntry] = {}
    pron = _pronunciations(cfg)
    recent = {str(x): i for i, x in enumerate(context.get("recent") or [])}
    running = {normalize(x) for x in context.get("running") or []}

    def add(entry_id: str, label: str, kind: str, actions: Iterable[str], *extra: str) -> None:
        names = {label, *extra}
        aliases = set()
        for name in names:
            aliases.update(spoken_forms(name))
        for heard, (target, count) in pron.items():
            if target == entry_id or normalize(target) == normalize(label):
                aliases.add(heard)
                # Подтверждённое обучение повышает приоритет, но не обходит пороги.
                extra_priority = min(0.15, count * 0.02)
                break
        else:
            extra_priority = 0.0
        pri = extra_priority + (0.10 if entry_id in recent else 0.0)
        if any(normalize(a) in running or normalize(label) in running for a in aliases):
            pri += 0.12
        entries[entry_id] = LexiconEntry(entry_id, label, kind, tuple(sorted(aliases)),
                                         frozenset(actions), pri)

    aliases = ((cfg.get("system") or {}).get("app_aliases") or {})
    for name, target in aliases.items():
        stem = re.sub(r"\.exe$", "", str(target), flags=re.I)
        add(f"app:{normalize(name)}", str(name), "app", ("open", "launch", "close"), stem, str(target))
    for key, path in (cfg.get("paths") or {}).items():
        if path:
            add(f"app:{normalize(key)}", str(key), "app", ("open", "launch", "close"), str(path).rsplit("\\", 1)[-1])
    # Известные лаунчеры — это источники данных/пути, а не список искажений.
    for name in ("steam", "discord", "telegram", "chrome", "genshin", "minecraft", "prism"):
        add(f"app:{name}", name, "app", ("open", "launch", "close"))
    by_game: dict[str, list[str]] = defaultdict(list)
    for name, appid in (cfg.get("games") or {}).items():
        by_game[str(appid)].append(str(name))
    for appid, names in by_game.items():
        label = names[0]
        add(f"game:{appid}", label, "game", ("open", "launch", "close"), *names[1:])
    for name, url in (cfg.get("sites") or {}).items():
        if url:
            add(f"site:{normalize(name)}", str(name), "site", ("open", "search"))
    for name, url in (cfg.get("urls") or {}).items():
        if url:
            add(f"url:{normalize(name)}", str(name), "site", ("open", "search"))
    for row in (cfg.get("commands") or []):
        if isinstance(row, dict) and row.get("phrase") and row.get("target"):
            add(f"command:{normalize(str(row['phrase']))}", str(row["phrase"]), "command",
                ("open", "launch"), str(row["target"]))
    for name, path in (context.get("folders") or {}).items():
        if path:
            add(f"folder:{normalize(name)}", str(name), "folder", ("open", "search"), str(path))
    for name in context.get("files") or []:
        if name:
            add(f"file:{normalize(str(name))}", str(name), "file", ("open",))
    for title in context.get("windows") or []:
        if title:
            add(f"window:{normalize(str(title))}", str(title), "window", ("close",))
    return Lexicon(list(entries.values()), dict(DEFAULT_VERBS))


@dataclass(frozen=True)
class Candidate:
    entry: LexiconEntry
    score: float
    heard: str


@dataclass(frozen=True)
class Decision:
    intent: str | None
    slot_id: str | None
    text: str
    confidence: float
    action: str                 # execute | confirm | clarify | ignore
    alternatives: tuple[str, ...] = ()
    reason: str = ""


def _best_verb(text: str, lexicon: Lexicon) -> tuple[str | None, str, float, str]:
    ts = words(text)
    if not ts:
        return None, "", 0.0, normalize(text)
    best = (None, "", 0.0, normalize(text))
    for intent, forms in lexicon.verbs.items():
        # Глагол ищем по всей фразе: STT ставит междометия/обращения в начало
        # («ну давай открой ютуб»), ранний вариант с ts[:3] терял его.
        for index, token in enumerate(ts):
            score = max((phonetic_similarity(token, form) for form in forms), default=0.0)
            if score > best[2]:
                rest = " ".join(ts[:index] + ts[index + 1:])
                best = (intent, token, score, rest)
    return best


def _best_slots(slot_text: str, intent: str, lexicon: Lexicon, acoustic: float) -> list[Candidate]:
    allowed = _ACTION_KINDS.get(intent)
    if not allowed or not normalize(slot_text):
        return []
    slot_words = [w for w in words(slot_text) if len(w) >= 3]
    candidates = []
    for entry in lexicon.entries:
        if entry.kind not in allowed or intent not in entry.actions:
            continue
        similarity = max((phonetic_similarity(slot_text, alias) for alias in entry.aliases), default=0.0)
        # STT разбавляет слот хвостовыми словами («ну давай ютуб», «открой ютуб
        # пожалуйста»): целофразовое сравнение тонет в них и слот терялся.
        # Сравниваем ещё и по отдельным словам — берём лучшее из двух.
        for w in slot_words:
            similarity = max(similarity,
                             max((phonetic_similarity(w, alias) for alias in entry.aliases),
                                 default=0.0))
        # Акустическая уверенность не должна превращать произвольное слово в
        # объект: сначала нужен правдоподобный фонетический кандидат.
        if similarity < 0.52:
            continue
        # Фонетика главнее, но STT confidence и динамический приоритет участвуют.
        score = 0.73 * similarity + 0.20 * max(0.0, min(1.0, acoustic)) + 0.07 * entry.priority
        candidates.append(Candidate(entry, min(1.0, score), slot_text))
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def _policy(intent: str, score: float, gap: float, cfg: dict) -> str:
    policy = cfg.get("understanding") or {}
    high = float(policy.get("high_confidence", 0.82))
    medium = float(policy.get("medium_confidence", 0.62))
    minimum = float(policy.get("minimum_confidence", 0.44))
    risk = _RISK.get(intent, "medium")
    if score < minimum:
        return "ignore"
    if gap < 0.07:
        return "clarify"
    if risk == "safe":
        return "execute" if score >= medium else "clarify"
    if risk == "medium":
        return "execute" if score >= high else "confirm"
    return "clarify"


def understand(hypotheses: Iterable[Hypothesis | dict | tuple | str], context: dict | None = None,
               cfg: dict | None = None, lexicon: Lexicon | None = None) -> Decision:
    """Выбрать интент и слот по n-best гипотезам всех движков.

    Ответ не исполняет команды. При отсутствии кандидата возвращается ``ignore``;
    вызывающий слой решает, сказать ли «не расслышал» (только когда фраза была
    адресована Джарвису) или проигнорировать постороннюю речь.
    """
    cfg, context = cfg or {}, context or {}
    lexicon = lexicon or build_lexicon(cfg, context)
    parsed: list[Hypothesis] = []
    for h in hypotheses:
        if isinstance(h, Hypothesis):
            parsed.append(h)
        elif isinstance(h, str):
            parsed.append(Hypothesis(h))
        elif isinstance(h, dict):
            parsed.append(Hypothesis(str(h.get("text") or ""), float(h.get("confidence") or 0.0),
                                     str(h.get("engine") or "unknown")))
        else:
            text, confidence, *rest = h
            parsed.append(Hypothesis(str(text), float(confidence), str(rest[0]) if rest else "unknown"))
    votes: dict[tuple[str, str], float] = defaultdict(float)
    texts: dict[tuple[str, str], str] = {}
    by_key: dict[tuple[str, str], list[float]] = defaultdict(list)
    for hyp in parsed:
        intent, _heard_verb, verb_score, slot_text = _best_verb(hyp.text, lexicon)
        if not intent or verb_score < 0.62:
            continue
        slots = _best_slots(slot_text, intent, lexicon, hyp.confidence)
        if not slots:
            # Пустой слот — переспрос («закрой» → «что закрыть?»). Непохожий
            # слот — ничего не выполняем: это может быть посторонняя речь.
            if intent in _ACTION_KINDS and not normalize(slot_text):
                return Decision(intent, None, normalize(hyp.text), verb_score, "clarify", (), "нет слота")
            continue
        top = slots[0]
        key = (intent, top.entry.id)
        combined = 0.35 * verb_score + 0.65 * top.score
        votes[key] += combined * max(0.25, hyp.confidence)
        by_key[key].append(combined)
        texts[key] = f"{DEFAULT_VERBS.get(intent, (intent,))[0]} {top.entry.label}"
    if not votes:
        return Decision(None, None, "", 0.0, "ignore", (), "нет кандидата")
    ranking = sorted(votes, key=votes.get, reverse=True)
    key = ranking[0]
    raw = votes[key]
    support = len(by_key[key])
    # Консенсус разных/нескольких гипотез повышает, но не может перешагнуть 1.0.
    score = min(1.0, raw / max(1, support) + min(0.10, 0.03 * (support - 1)))
    second = votes[ranking[1]] / max(1, len(by_key[ranking[1]])) if len(ranking) > 1 else 0.0
    intent, slot_id = key
    action = _policy(intent, score, score - second, cfg)
    alternatives = tuple(lexicon_entry.label for lexicon_entry in
                         (next(e for e in lexicon.entries if e.id == k[1]) for k in ranking[:2])
                         if lexicon_entry.id != slot_id)
    return Decision(intent, slot_id or None, texts[key], score, action, alternatives,
                    f"hypotheses={support}; gap={score - second:.2f}")


def generated_phrases(lexicon: Lexicon, limit: int | None = None) -> list[tuple[str, str, str]]:
    """Детерминированная матрица «глагол × объект» для offline/CI оценки."""
    rows = []
    for intent, forms in lexicon.verbs.items():
        allowed = _ACTION_KINDS.get(intent)
        if not allowed:
            continue
        for entry in lexicon.entries:
            if entry.kind not in allowed or intent not in entry.actions:
                continue
            for verb in forms:
                for form in entry.aliases[:min(4, len(entry.aliases))]:
                    rows.extend(((f"{verb} {form}", intent, entry.id),
                                 (f"джарвис {verb} {form}", intent, entry.id),
                                 (f"{verb} {form} джарвис", intent, entry.id)))
                    if limit and len(rows) >= limit:
                        return rows[:limit]
    return rows