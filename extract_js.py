import re

with open('frontend/views/index.hbs', 'r', encoding='utf-8') as f:
    content = f.read()

scripts = re.findall(r'<script>(.*?)</script>', content, flags=re.DOTALL)
for i, script in enumerate(scripts):
    with open(f'test_script_{i}.js', 'w', encoding='utf-8') as js_f:
        js_f.write(script)
