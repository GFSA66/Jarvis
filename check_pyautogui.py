import pyautogui, inspect
print("pyautogui", pyautogui.__version__)
print("clipboard funcs:", [n for n in dir(pyautogui) if "clip" in n.lower()])
print("hotkey sig:", inspect.signature(pyautogui.hotkey))
