import pathlib
p = pathlib.Path("jarvis_settings.py")
t = p.read_text(encoding="utf-8")
fixes = [
    ('card = self._card(sf, "Слово-активатор", 1)',
     'card = self._card(sf, "Слово-активатор", 2)'),
    ('card = self._card(sf, "Chrome", 2)',
     'card = self._card(sf, "Chrome", 3)'),
    ('card = self._card(sf, "Планировщик заданий Windows", 3)',
     'card = self._card(sf, "Планировщик заданий Windows", 4)'),
    ('card = self._card(sf, "Фразы управления", 4)',
     'card = self._card(sf, "Фразы управления", 5)'),
]
c = 0
for a, b in fixes:
    if a in t:
        t = t.replace(a, b)
        c += 1
print("rows fixed:", c)
p.write_text(t, encoding="utf-8")
