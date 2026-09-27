with open("backend/main.py", "r") as f:
    text = f.read()

calendar_rule = """       - REMINDERS & SCHEDULING: If the user asks to "remind me to...", "schedule an event", or do something at a specific future time (e.g., "tomorrow at 2pm"), DO NOT write a local shell script with 'sleep'. Instead, YOU MUST target Google Calendar. Set requires_browser=true and construct the deep link: "https://calendar.google.com/calendar/render?action=TEMPLATE&text=[URL_ENCODED_TITLE]&details=[URL_ENCODED_DETAILS]". For the date/time, either parse it into the URL or leave it for the user to fill out in the browser.
"""

if "- DEEP LINKING: For multi-step web actions" in text:
    text = text.replace(
        '- DEEP LINKING: For multi-step web actions (e.g., "open gmail... draft email..."), construct the exact deep link!',
        '- DEEP LINKING: For multi-step web actions (e.g., "open gmail... draft email..."), construct the exact deep link!\n' + calendar_rule
    )
else:
    print("Could not find the hook for the rule.")

# Now for the middleware
middleware_hook = """
            # Explicit Deep Link Interceptor for weak models (like Llama 8B)
"""

calendar_middleware = """
            # Explicit Deep Link Interceptor for Scheduling/Reminders
            if any(word in prompt_lower for word in ["remind", "schedule", "calendar"]):
                import urllib.parse
                logger.info("Middleware hijacked Reminder intent to enforce Google Calendar Deep Linking.")
                structured_data["requires_browser"] = True
                structured_data["shell_script"] = None
                
                # Extract simple title
                title = request.natural_language_prompt
                if "remind me to" in prompt_lower:
                    title = request.natural_language_prompt[prompt_lower.index("remind me to")+12:].strip()
                elif "remind me" in prompt_lower:
                    title = request.natural_language_prompt[prompt_lower.index("remind me")+9:].strip()
                
                encoded_title = urllib.parse.quote(title.capitalize())
                structured_data["target_url"] = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={encoded_title}&details=Automated+reminder+created+by+OmniShell."
"""

if middleware_hook in text:
    text = text.replace(middleware_hook, calendar_middleware + middleware_hook)
else:
    print("Could not find the middleware hook.")

with open("backend/main.py", "w") as f:
    f.write(text)

