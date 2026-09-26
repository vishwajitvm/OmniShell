import re

with open('README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

# Fix the broken backticks in the setup block
readme = re.sub(r' ash', '`ash', readme)
readme = re.sub(r'\n', '`\n', readme)

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(readme)

print("Fixed code block syntax correctly.")
