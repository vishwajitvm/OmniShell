import webbrowser, time, pyautogui
webbrowser.open('https://calendar.google.com/calendar/render?action=TEMPLATE&text=Call+Manager&dates=20261001T160000Z/20261001T170000Z')
time.sleep(6)
pyautogui.hotkey('ctrl', 's')
