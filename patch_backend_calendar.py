import re

with open("backend/main.py", "r") as f:
    text = f.read()

# Remove the bad middleware
middleware_regex = r"# Explicit Deep Link Interceptor for Scheduling/Reminders.*?structured_data\[\"target_url\"\] = [^\n]+\n"
text = re.sub(middleware_regex, "", text, flags=re.DOTALL)

# Add current time to the system prompt
prompt_injection = """
    You must simulate a highly advanced discussion between SIX distinct agents:"""

new_prompt_injection = """
    CURRENT SYSTEM TIME: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    
    You must simulate a highly advanced discussion between SIX distinct agents:"""

text = text.replace(prompt_injection, new_prompt_injection)

# Add datetime import if missing
if "import datetime" not in text:
    text = text.replace("import json", "import json\nimport datetime")

# Update the calendar rule
old_rule = """       - REMINDERS & SCHEDULING: If the user asks to "remind me to...", "schedule an event", or do something at a specific future time (e.g., "tomorrow at 2pm"), DO NOT write a local shell script with 'sleep'. Instead, YOU MUST target Google Calendar. Set requires_browser=true and construct the deep link: "https://calendar.google.com/calendar/render?action=TEMPLATE&text=[URL_ENCODED_TITLE]&details=[URL_ENCODED_DETAILS]". For the date/time, either parse it into the URL or leave it for the user to fill out in the browser."""

new_rule = """       - REMINDERS & SCHEDULING: If the user asks to "remind me to...", "schedule", or do something at a specific future time (e.g., "tomorrow at 4pm"), YOU MUST target Google Calendar.
         * You know the current time, so CALCULATE the exact future date/time. Format it as YYYYMMDDTHHmmssZ/YYYYMMDDTHHmmssZ (e.g., 20261001T160000Z/20261001T170000Z).
         * Construct the URL: "https://calendar.google.com/calendar/render?action=TEMPLATE&text=[ENCODED_TITLE]&dates=[DATES]"
         * The user DEMANDED that you automatically save the event. To do this on Linux/Windows, DO NOT set requires_browser=true. Instead, set requires_browser=false and write a Python shell script that uses `webbrowser.open("URL")`, sleeps for 5 seconds to let the browser load, and then uses `pyautogui` (install it via `pip install pyautogui --break-system-packages` if needed, or catch import error and install it in the script) to press 'ctrl' + 's' to save the Google Calendar event automatically!"""

if old_rule in text:
    text = text.replace(old_rule, new_rule)
else:
    print("Could not find old rule.")

with open("backend/main.py", "w") as f:
    f.write(text)

