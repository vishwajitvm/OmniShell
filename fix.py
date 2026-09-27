import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace with backticks to completely avoid newline escaping issues in JS
code = re.sub(r'innerText = "// Web Execution intent intercepted\nLaunch Browser: "\s*\+\s*data\.target_url;', 
              'innerText = // Web Execution intent intercepted\\nLaunch Browser: ;', code)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Replaced with backticks")
