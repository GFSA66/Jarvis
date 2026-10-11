"""Проверка микрофона для Джарвиса. Запуск: python mic_test.py
Скажи фразу вроде «джарвис открой настройки и запусти стим» — 8 секунд записи.
Получишь mic_test.wav (послушай его!) и график громкости в консоли."""
import wave, audioop, sys
try:
    import pyaudio
except ImportError:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        sys.exit("Не нашёл pyaudio / pyaudiowpatch. Запускай внутри .venv Джарвиса.")

SECONDS = 8
pa = pyaudio.PyAudio()
dev = pa.get_default_input_device_info()
rate = int(dev["defaultSampleRate"])
print(f"Устройство: {dev['name']}  (частота {rate} Гц, каналов {dev['maxInputChannels']})")
if rate <= 16000:
    print("!! Низкая частота — похоже на Bluetooth-гарнитуру в режиме звонка: качество будет плохим.")
chunk = rate // 10
stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True, frames_per_buffer=chunk)
print(f"Говори {SECONDS} секунд…\n")
frames, levels = [], []
for _ in range(SECONDS * 10):
    data = stream.read(chunk, exception_on_overflow=False)
    frames.append(data)
    levels.append(audioop.rms(data, 2))
stream.stop_stream(); stream.close(); pa.terminate()

with wave.open("mic_test.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(b"".join(frames))

mx = max(levels) or 1
print("громкость по 0.1 с (чем длиннее полоска, тем громче):")
for i, l in enumerate(levels):
    print(f"{i/10:4.1f}с {l:5d} " + "#" * int(40 * l / mx))
print(f"\nФон (медиана): {sorted(levels)[len(levels)//2]}   Пик: {mx}")
print("Файл mic_test.wav сохранён рядом. Послушай: все слова слышны целиком и не тихие?")
print("Если слова слышны, а Джарвис их режет — виноват порог/обрезка в коде, а не микрофон.")
