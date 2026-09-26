import re

with open('backend/main.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix the literal newlines in the string
code = code.replace('"Hello,\n\nI will not be able to join the meeting today.\n\nBest regards."', '"Hello,\\n\\nI will not be able to join the meeting today.\\n\\nBest regards."')

with open('backend/main.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed syntax error")
