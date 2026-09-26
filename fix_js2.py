import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

# I will use a robust regex to fix ANY literal newline between the string quotes
# Actually, I'll just rewrite the block safely

safe_block = '''
                if (data.requires_browser && data.target_url) {
                    document.getElementById('powershell-output').innerText = "// Web Execution intent intercepted\\nLaunch Browser: " + data.target_url;
                } else {
                    document.getElementById('powershell-output').innerText = data.shell_script || "// Blocked by Security Agent";
                }
'''

# Use regex to find the block and replace it
code = re.sub(r'if \(data\.requires_browser && data\.target_url\).*?\} else \{.*?\}', safe_block.strip(), code, flags=re.DOTALL)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Replaced JS block safely")
