import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    code = f.read()

# I will replace the exact corrupted string literal block
bad_block = '''                  if (data.requires_browser && data.target_url) {
                    document.getElementById('powershell-output').innerText = "// Web Execution intent intercepted
Launch Browser: " + data.target_url;
                  } else {
                      document.getElementById('powershell-output').innerText = data.shell_script || "// Blocked by Security Agent";
                  }'''

good_block = '''                  if (data.requires_browser && data.target_url) {
                      document.getElementById('powershell-output').innerText = "// Web Execution intent intercepted\\nLaunch Browser: " + data.target_url;
                  } else {
                      document.getElementById('powershell-output').innerText = data.shell_script || "// Blocked by Security Agent";
                  }'''

code = code.replace(bad_block, good_block)

# Let's also catch the case with 2 spaces for "  Launch Browser:"
code = code.replace(bad_block.replace('\nLaunch', '\n  Launch'), good_block)

with open('frontend/views/index.hbs', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed the master corruption.")
