import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

replacement = '''
                if (data.requires_browser && data.target_url) {
                    document.getElementById('powershell-output').innerText = "// Web Execution intent intercepted\\nLaunch Browser: " + data.target_url;
                } else {
                    document.getElementById('powershell-output').innerText = data.shell_script || "// Blocked by Security Agent";
                }
'''

# Use an exact string replace to be 100% safe
code = code.replace(
    "document.getElementById('powershell-output').innerText = data.shell_script || \"// Blocked by Security Agent\";",
    replacement.strip()
)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Safely replaced.")
