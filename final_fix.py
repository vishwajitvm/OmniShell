import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

backtick = chr(96)
replacement = f'''
                if (data.requires_browser && data.target_url) {{
                    document.getElementById('powershell-output').innerText = {backtick}// Web Execution intent intercepted
Launch Browser: {backtick} + data.target_url;
                }} else {{
                    document.getElementById('powershell-output').innerText = data.shell_script || "// Blocked by Security Agent";
                }}
'''

code = code.replace(
    "document.getElementById('powershell-output').innerText = data.shell_script || \"// Blocked by Security Agent\";",
    replacement.strip()
)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)
