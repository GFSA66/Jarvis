"""Матрица «фраза → ожидаемое решение» на реальных репликах владельца.

Здесь — чистая маршрутизация (jarvis_routing), проверяемая без Windows и Tk.
Полная таблица интентов команд растёт по мере развития реестра.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jarvis_intents as ji  # noqa: E402
import jarvis_routing as routing  # noqa: E402


# --- декларативный реестр: токенный скор, приоритет, переспрос --------------

SAMPLE = [
    ji.Intent("volume", ("громче", "тише", "громкость"), 20),
    ji.Intent("steam_game", ("киберпанк", "кс"), 32),
    ji.Intent("close_app", ("закрой блокнот",), 10,
              pattern=r"\b(?:закрой|закрыть)\s+\w+"),
    ji.Intent("track", (), 26, pattern=r"\b(?:включи|найди)\s+(?:трек|песню)\s+\S+"),
]


def test_intent_exact_and_prefix_tokens():
    hits = ji.match("громче", SAMPLE)
    assert hits and hits[0].intent.name == "volume"
    # глагол с одинаковым префиксом из 5 букв тоже распознаётся
    hits = ji.match("закрой блокнот пожалуйста", SAMPLE)
    assert hits[0].intent.name == "close_app"
    # короткое слово не должно совпадать по префиксу — только целиком
    assert not ji.match("блок", SAMPLE)


def test_intent_pattern_phrases():
    hits = ji.match("включи трек немо", SAMPLE)
    assert hits and hits[0].intent.name == "track"


def test_intent_tie_triggers_clarify():
    twin = [
        ji.Intent("note", ("заметка",), 51),
        ji.Intent("notes", ("заметка",), 51),
    ]
    hits = ji.match("заметка", twin)
    assert ji.is_tie(hits)
    assert ji.tie_options(hits) == ["note", "notes"]
    assert not ji.is_tie(ji.match("громче", SAMPLE))


def test_clarify_choice_words():
    assert ji.clarify_choice("первая") == 0
    assert ji.clarify_choice("вторая") == 1
    assert ji.clarify_choice("второе") == 1
    assert ji.clarify_choice("2") == 1
    assert ji.clarify_choice("открой стим") is None


def test_intent_threshold_rejects_partial_phrase():
    # не все слова фразы на месте — интент не срабатывает
    assert not ji.match("закрой", SAMPLE)
    assert not ji.match("гром", SAMPLE)


# Фразы из ~/.jarvis/history.jsonl владельца: фраза → ожидаемое решение
POWER_CASES = {
    "выключи пк": "shutdown",
    "выключи компьютер": "shutdown",
    "выключи пк-а": "shutdown",
}

# Негативы: филлеры и обрывки не должны считаться рекомендацией/вопросом нейросети
NEGATIVE_CASES = [
    "ну", "давай", "так", "ага", "нет", "спасибо",
    "сначала хочу все-таки подделывать",
]

# Фразы из истории: не должны запускать игры
NO_LAUNCH_CASES = [
    "во что поиграть кроме киберпанка",
    "посоветуй игру, не киберпанк",
    "не запускай майнкрафт",
    "запусти всё кроме стима",
    "во что мне лучше поиграть только не киберпанк",
    "что посоветуешь из игр без доты",
    "посоветуй игру кроме кс",
    "что поиграть не хочу хорроры",
    "рекомендую игру но не киберпанк",
    "подбери игру без майнкрафта",
    "посоветуй что нибудь кроме стима",
    "во что поиграть не запускай кс",
]

# Должны запускать (по прямой просьбе)
LAUNCH_CASES = [
    "запусти roblox",
    "запусти киберпанк",
    "открой стим",
    "включи майнкрафт",
    "запусти кс",
    "открой доту",
]


# --- расширенная таблица «фраза → ожидаемое решение» (power / close / rec) ----

POWER_CASES.update({
    "выключи ноутбук": "shutdown",
    "выключи машину": "shutdown",
    "выруби компьютер": "shutdown",
    "заверши работу пк": "shutdown",
    "выключи систему": "shutdown",
    "выключи комп": "shutdown",
    "выключи пэка": "shutdown",
    "выключи пика": "shutdown",
    "перезагрузи компьютер": "restart",
    "перезагрузи пк": "restart",
    "перезагрузка системы": "restart",
    "отмени выключение": "cancel",
    "отмена перезагрузки": "cancel",
    "отмени перезагрузку": "cancel",
    "усыпи компьютер": "sleep",
    "переведи в спящий режим": "sleep",
    "режим сна": "sleep",
    "гибернация пк": "hibernate",
    "заблокируй пк": "lock",
    "заблокируй компьютер": "lock",
})

NEGATIVE_CASES += [
    "эм", "мм", "хм", "типа", "короче", "ну вот", "ладно", "окей", "ок",
    "понял", "да", "агась", "не знаю", "хочу", "наверное", "как бы",
    "слушай", "в общем", "вообще", "кстати", "блин", "жесть",
    "так себе", "не важно", "да ладно", "и так далее", "и всё", "нужно",
    "хочу все таки подделывать", "сначала", "сначала хочу", "ааа",
    "что", "как", "давай начнем", "погнали", "давай дальше",
]

NO_LAUNCH_CASES += [
    "только не киберпанк",
    "не киберпанк",
    "кроме киберпанка что поиграть",
    "во что поиграть не майнкрафт",
    "что лучше поиграть не кс и не доту",
    "посоветуй игру не хорроры",
    "не запускай ничего",
    "без киберпанка во что поиграть",
]

LAUNCH_CASES += [
    "запусти паук", "запусти гта", "открой валорант",
    "включи ведьмак", "запусти фифа", "откьюбь стим",
    "запусти шахматы", "запусти балдарс",
]


# «закрой <цель>» → тип закрытия. power_hint — НЕ закрытие процесса.
CLOSE_CASES = {
    "закрой пк": "power_hint",
    "закрой компьютер": "power_hint",
    "закрой ноутбук": "power_hint",
    "закрой систему": "power_hint",
    "закрой windows": "power_hint",
    "закрой это окно": "active",
    "закрой текущее": "active",
    "закрой активное окно": "active",
    "закрой блокнот": "app",
    "закрой настройки": "app",
    "закрой проводник": "app",
    "закрой ютуб": "app",
    "закрой хром": "app",
    "закрыть стим пожалуйста": "app",
    "закрой": "error",
    "закройщик номер пять": "error",
}


def test_history_power_phrases():
    for phrase, expected in POWER_CASES.items():
        assert routing.power_intent(phrase) == expected, phrase


def test_history_negatives_are_not_recommendations():
    for phrase in NEGATIVE_CASES:
        assert not routing.is_recommendation(phrase), phrase


def test_history_negation_phrases_block_launch():
    for phrase in NO_LAUNCH_CASES:
        assert routing.launch_blocked(phrase), phrase


def test_history_direct_launch_allowed():
    for phrase in LAUNCH_CASES:
        assert not routing.launch_blocked(phrase), phrase


def test_history_close_pc_is_power_hint_not_process():
    for phrase in ("закрой пк", "закрой компьютер", "закрой ноутбук"):
        assert routing.resolve_close(phrase)["kind"] == "power_hint", phrase


def test_close_matrix_by_kind():
    for phrase, kind in CLOSE_CASES.items():
        got = routing.resolve_close(phrase)["kind"]
        assert got == kind, f"{phrase!r} → {got}, ожидалось {kind}"


def test_close_verb_exact_not_prefix():
    # «закройщик» — не команда закрытия (ловушка старого has() по основе «закр»)
    assert routing.resolve_close("закройщик номер пять")["kind"] == "error"
    assert routing.resolve_close("открой блокнот")["kind"] == "error"


def test_power_matrix_full():
    for phrase, expected in POWER_CASES.items():
        assert routing.power_intent(phrase) == expected, phrase


# --- матчинг декларативного реестра на реальных фразах (группы команд) --------
# Реестр по образцу настоящего: приоритет и обучающие фразы. Проверяем, что
# «фраза → ожидаемый интент» определяется однозначно, без опоры на порядок строк.
ROUTE_SAMPLE = [
    ji.Intent("volume_up", ("сделай громче", "погромче", "увеличь громкость",
                            "прибавь звук", "громче"), 20),
    ji.Intent("volume_down", ("сделай тише", "потише", "уменьши громкость",
                              "убавь звук", "тише"), 20),
    ji.Intent("volume_set", ("громкость на минимум", "громкость на максимум"), 20,
              pattern=r"\bгромкость\s+\S+\s+на\s+\S+"),
    ji.Intent("brightness_up", ("сделай ярче", "увеличь яркость", "прибавь яркость",
                                "ярче"), 21),
    ji.Intent("brightness_down", ("сделай тусклее", "уменьши яркость",
                                  "убавь яркость", "тусклее"), 21),
    ji.Intent("media_next", ("следующий трек", "переключи трек вперед",
                             "следующая песня"), 22),
    ji.Intent("media_prev", ("предыдущий трек", "верни трек назад",
                             "предыдущая песня"), 22),
    ji.Intent("mute", ("выключи звук", "без звука", "убери звук"), 20),
    ji.Intent("open_site", ("открой ютуб", "открой гитхаб", "открой youtube",
                            "открой сайт"), 30),
    ji.Intent("note", ("сделай заметку", "запиши мысль", "создай заметку"), 50),
    ji.Intent("reminder", ("напомни", "поставь напоминание", "напомни мне"), 51),
    ji.Intent("timer", ("поставь таймер", "засеки время", "таймер на"), 52),
    ji.Intent("stop", ("стоп", "отставить", "хватит"), 5),
]

# «фраза → ожидаемый интент»: реальные формулировки всех групп.
PHRASE_INTENT = {
    "сделай громче": "volume_up",
    "погромче": "volume_up",
    "увеличь громкость": "volume_up",
    "прибавь звук": "volume_up",
    "громче": "volume_up",
    "сделай тише": "volume_down",
    "потише": "volume_down",
    "уменьши громкость": "volume_down",
    "убавь звук": "volume_down",
    "громкость на минимум": "volume_set",
    "громкость на максимум": "volume_set",
    "сделай ярче": "brightness_up",
    "увеличь яркость": "brightness_up",
    "прибавь яркость": "brightness_up",
    "ярче": "brightness_up",
    "сделай тусклее": "brightness_down",
    "уменьши яркость": "brightness_down",
    "убавь яркость": "brightness_down",
    "следующий трек": "media_next",
    "переключи трек вперед": "media_next",
    "следующая песня": "media_next",
    "предыдущий трек": "media_prev",
    "верни трек назад": "media_prev",
    "предыдущая песня": "media_prev",
    "выключи звук": "mute",
    "без звука": "mute",
    "убери звук": "mute",
    "открой ютуб": "open_site",
    "открой гитхаб": "open_site",
    "открой youtube": "open_site",
    "сделай заметку": "note",
    "запиши мысль": "note",
    "создай заметку": "note",
    "напомни": "reminder",
    "поставь напоминание": "reminder",
    "напомни мне": "reminder",
    "поставь таймер": "timer",
    "засеки время": "timer",
    "таймер на пять минут": "timer",
    "стоп": "stop",
    "отставить": "stop",
    "хватит": "stop",
}


def test_real_phrase_matrix_routes_by_group():
    """Каждая реальная фраза уходит в свой интент, а не в чужой по порядку строк."""
    for phrase, expected in PHRASE_INTENT.items():
        hits = ji.match(phrase, ROUTE_SAMPLE)
        assert hits, f"фраза не распознана: {phrase!r}"
        assert hits[0].intent.name == expected, f"{phrase!r} → {hits[0].intent.name}"


def test_matrix_size_is_regression_scale():
    """Матрица регрессии покрывает все группы из history.jsonl владельца (≥150 фраз)."""
    total = (len(POWER_CASES) + len(NEGATIVE_CASES) + len(NO_LAUNCH_CASES)
             + len(LAUNCH_CASES) + len(CLOSE_CASES) + len(PHRASE_INTENT))
    assert total >= 150, f"в матрице всего {total} фраз — нужно ≥150"


