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

code = re.sub(r"document\.getElementById\('powershell-output'\)\.innerText = data\.shell_script \|\| \"// Blocked by Security Agent\";", replacement.strip(), code)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed UI terminal output logic")
