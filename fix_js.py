import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace the literal newline with \n in the JS string
code = code.replace('// Web Execution intent intercepted\n  Launch Browser: ', '// Web Execution intent intercepted\\nLaunch Browser: ')

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed JS Syntax Error")
