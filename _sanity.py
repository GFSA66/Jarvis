import jarvis_utils as u
print(u.parse_number_ru('громкость на тридцать'), u.parse_number_ru('30'), u.parse_number_ru('сто'))
print(u.parse_duration_ru('2 часа 15 минут'), u.parse_duration_ru('полтора часа'), u.parse_duration_ru('полчаса'), u.parse_duration_ru('через час'), u.parse_duration_ru('пять минут'))
print(u.parse_clock_ru('на 7:30'), u.parse_clock_ru('в 9 утра'))
print(u.apply_dictation_commands('привет запятая как дела', '', True))
print(u.apply_dictation_commands('удали последнее слово', 'привет мир'))
print(u.roll_dice('4d6'))
print(u.is_dictation_text(True, 'поставь громче'), u.dictation_mode_detect('закончить диктовку'))

