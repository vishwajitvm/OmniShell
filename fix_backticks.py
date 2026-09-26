import re

with open('README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

# I will strictly replace the broken parts using raw python strings and chr(96)
backticks = chr(96) * 3

readme = re.sub(r' ash', f'{backticks}bash', readme)
# Replace standalone backticks on a newline (which PowerShell broke) with triple backticks
readme = re.sub(r'\n\n', f'\n{backticks}\n', readme)
# Clean up any trailing backticks from the previous bug
readme = re.sub(r'\n', '\n', readme)
# And replace the triple backticks again because the previous step might have eaten one
readme = re.sub(r'\n`ash\n', f'\n{backticks}bash\n', readme)

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(readme)

print("Fixed using chr(96)")
