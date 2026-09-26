import re

with open('backend/main.py', 'r', encoding='utf-8') as f:
    code = f.read()

middleware_code = '''
            # --- AGENTIC MIDDLEWARE INTERCEPTOR ---
            prompt_lower = request.natural_language_prompt.lower()
            
            # Explicit Deep Link Interceptor for weak models (like Llama 8B)
            if "gmail" in prompt_lower and ("draft" in prompt_lower or "email" in prompt_lower):
                import urllib.parse
                
                # Extract basic info heuristically
                to_email = ""
                emails = [word for word in prompt_lower.split() if "@" in word]
                if emails:
                    to_email = emails[0].strip("',.")
                
                # Hard fallback URL construction
                base_url = "https://mail.google.com/mail/?view=cm&fs=1"
                if to_email:
                    base_url += f"&to={to_email}"
                
                # Add a generic professional body
                body_text = "Hello,\\n\\nI will not be able to join the meeting today.\\n\\nBest regards."
                if "cannot" in prompt_lower and "meeting" in prompt_lower:
                    base_url += f"&su=Meeting&body={urllib.parse.quote(body_text)}"
                
                logger.info("Middleware hijacked Gmail intent to enforce Deep Linking.")
                structured_data["requires_browser"] = True
                structured_data["target_url"] = base_url
                structured_data["shell_script"] = ""
            else:
                web_keywords = {
                    "spotify": "https://open.spotify.com", 
                    "netflix": "https://www.netflix.com", 
                    "github": "https://github.com", 
                    "youtube": "https://www.youtube.com"
                }
                
                forced_url = None
                for kw, url in web_keywords.items():
                    if kw in prompt_lower:
                        forced_url = url
                        break
                        
                if forced_url or "browser" in prompt_lower or "http" in prompt_lower or "website" in prompt_lower:
                    structured_data["requires_browser"] = True
                    if not structured_data.get("target_url") or "google.com" in structured_data.get("target_url", ""):
                        structured_data["target_url"] = forced_url if forced_url else "https://www.google.com"
            # --------------------------------------
'''

# Find the interceptor block and replace it
code = re.sub(r'# --- AGENTIC MIDDLEWARE INTERCEPTOR ---.*?# --------------------------------------', middleware_code.strip(), code, flags=re.DOTALL)

with open('backend/main.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Injected explicit Gmail Deep Link interceptor.")
