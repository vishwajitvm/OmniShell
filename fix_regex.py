import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace all occurrences of the broken string literal
code = re.sub(r'innerText = "// Web Execution intent intercepted[\s\S]*?Launch Browser: "\s*\+\s*data\.target_url;', 
              'innerText = "// Web Execution intent intercepted\\nLaunch Browser: " + data.target_url;', 
              code)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Applied Regex Fix")
