with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

target = 'intercepted\nLaunch Browser: "'
replacement = 'intercepted\\nLaunch Browser: "'
code = code.replace(target, replacement)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Forced string replace!")
