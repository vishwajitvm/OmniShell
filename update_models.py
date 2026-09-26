import re
with open('backend/main.py', 'r') as f:
    code = f.read()

models = '''FALLBACK_MODELS = [
    "openrouter/google/gemini-2.0-flash-exp:free",
    "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    "openrouter/nvidia/llama-3.1-nemotron-70b-instruct:free",
    "groq/llama-3.3-70b-versatile",
    "openrouter/meta-llama/llama-3.1-8b-instruct",
    "gemini/gemini-1.5-flash"
]'''

code = re.sub(r'FALLBACK_MODELS = \[.*?\]', models, code, flags=re.DOTALL)
with open('backend/main.py', 'w') as f:
    f.write(code)
print("Updated models")
