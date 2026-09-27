import http.server
import socketserver
import json
import subprocess
import threading
import sys
import platform
import os
import psutil
import time

PORT = 8003

def verify_process(process_name):
    if not process_name:
        return True # Skip if no process specified
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and process_name.lower() in proc.info['name'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def get_installed_browsers():
    browsers = set()
    system = platform.system().lower()
    
    if system == "windows":
        try:
            import winreg
            browsers.add("Edge") # Default Windows
            path = r"SOFTWARE\Clients\StartMenuInternet"
            
            for hkey in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    with winreg.OpenKey(hkey, path) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            browser_key = winreg.EnumKey(key, i)
                            try:
                                with winreg.OpenKey(key, f"{browser_key}\\Capabilities") as cap_key:
                                    name = winreg.QueryValueEx(cap_key, "ApplicationName")[0]
                                    browsers.add(name)
                            except FileNotFoundError:
                                browsers.add(browser_key)
                except FileNotFoundError:
                    continue
        except Exception as e:
            print("Windows Registry scan failed:", e)
            
    elif system == "linux":
        # Search for common Linux browsers in PATH
        common_browsers = {
            "google-chrome": "Google Chrome",
            "brave-browser": "Brave",
            "firefox": "Firefox",
            "chromium": "Chromium"
        }
        for cmd, name in common_browsers.items():
            if subprocess.call(["which", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                browsers.add(name)
        if not browsers:
            browsers.add("Default Browser (xdg-open)")
    
    return list(browsers)

import uuid

def execute_script(script):
    system = platform.system().lower()
    print(f"\n[EXECUTION AGENT] Dispatching to OS: {system.upper()}")
    
    try:
        if system == "windows":
            exec_id = uuid.uuid4().hex
            payload_path = os.path.abspath(f"payload_{exec_id}.ps1")
            wrapper_path = os.path.abspath(f"wrapper_{exec_id}.ps1")
            out_path = os.path.abspath(f"out_{exec_id}.json")
            
            with open(payload_path, "w", encoding="utf-8") as f:
                f.write(script)
                
            wrapper_code = f"""
$ErrorActionPreference = 'Continue'
Clear-Host
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "           🤖 AGENTIC AUTOMATION SYSTEM          " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "`n[Auto-Executing Script]" -ForegroundColor Yellow

try {{
    $result = & "{payload_path}" *>&1
    if ($result) {{ Write-Host $result }}
    Write-Host "`n[✅] TASK DONE 100%" -ForegroundColor Green
    $outData = @{{ status = "success"; output = ($result | Out-String) }}
}} catch {{
    Write-Host "`n[❌] TASK FAILED: $_" -ForegroundColor Red
    $outData = @{{ status = "error"; output = $_.Exception.Message }}
}}

$outData | ConvertTo-Json -Compress | Set-Content "{out_path}"

Write-Host "`nClosing terminal in 4 seconds..." -ForegroundColor DarkGray
Start-Sleep -Seconds 4
"""
            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write(wrapper_code)
                
            # DYNAMIC FIX: Bypass cmd.exe entirely. Use native Windows process creation flags to spawn a flawless new console.
            # This completely eliminates quoting bugs (like the \\ error).
            CREATE_NEW_CONSOLE = 0x00000010
            proc = subprocess.Popen(
                ["powershell.exe", "-ExecutionPolicy", "Bypass", "-NoProfile", "-WindowStyle", "Normal", "-File", wrapper_path],
                creationflags=CREATE_NEW_CONSOLE
            )
            proc.wait() # Wait for the new visual console to close
            
            output_text = "(Execution completed. No output captured or script failed to launch.)"
            if os.path.exists(out_path):
                try:
                    with open(out_path, "r", encoding="utf-8") as f:
                        res = json.load(f)
                        if res.get("output") and res["output"].strip():
                            output_text = res["output"].strip()
                        elif res.get("status") == "success":
                            output_text = "(Command executed successfully but returned no text output.)"
                except Exception:
                    pass
                os.remove(out_path)
                
            if os.path.exists(payload_path): os.remove(payload_path)
            if os.path.exists(wrapper_path): os.remove(wrapper_path)
            
            return output_text
        elif system == "linux":
            # DYNAMIC FIX: For Ubuntu/Linux, dynamically find the available terminal emulator to pop up a visual terminal.
            exec_id = uuid.uuid4().hex
            payload_path = os.path.abspath(f"payload_{exec_id}.sh")
            wrapper_path = os.path.abspath(f"wrapper_{exec_id}.sh")
            out_path = os.path.abspath(f"out_{exec_id}.json")
            
            with open(payload_path, "w", encoding="utf-8") as f:
                f.write(script)
                
            wrapper_code = f"""#!/bin/bash
set -x
clear
echo -e "\e[36m==================================================\e[0m"
 -e "\\e[36m==================================================\\e[0m"
echo -e "\\e[36m           🤖 AGENTIC AUTOMATION SYSTEM          \\e[0m"
echo -e "\\e[36m==================================================\\e[0m"
echo -e "\\e[33m\\n[Auto-Executing Script]\\e[0m"

# Run it so the user can see if it prompts for anything!
output=$(bash "{payload_path}" 2>&1 | tee /dev/tty)
exit_code=${PIPESTATUS[0]}

if [ $exit_code -eq 0 ]; then
    echo "$output"
    echo -e "\\n\\e[32m[✅] TASK DONE 100%\\e[0m"
    echo "{{\\"status\\":\\"success\\",\\"output\\":$(jq -Rsa . <<< "$output")}}" > "{out_path}"
else
    echo -e "\\n\\e[31m[❌] TASK FAILED: $output\\e[0m"
    echo "{{\\"status\\":\\"error\\",\\"output\\":$(jq -Rsa . <<< "$output")}}" > "{out_path}"
fi

echo -e "\\e[90m\\nClosing terminal in 4 seconds...\\e[0m"
sleep 4
"""
            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write(wrapper_code)
            os.chmod(wrapper_path, 0o755)
            os.chmod(payload_path, 0o755)
            
            # Detect terminal
            terminals = ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]
            term_cmd = None
            for term in terminals:
                if subprocess.call(["which", term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                    term_cmd = term
                    break
            
            if term_cmd:
                if term_cmd == "gnome-terminal":
                    proc = subprocess.Popen([term_cmd, "--", "bash", "-c", wrapper_path])
                else:
                    proc = subprocess.Popen([term_cmd, "-e", wrapper_path])
                proc.wait()
            else:
                # Fallback to silent execution if no visual terminal available
                subprocess.run(['/bin/bash', '-c', wrapper_path])
                
            output_text = "(Execution completed.)"
            if os.path.exists(out_path):
                try:
                    with open(out_path, "r", encoding="utf-8") as f:
                        res = json.load(f)
                        output_text = res.get("output", output_text).strip()
                except Exception: pass
                os.remove(out_path)
            
            if os.path.exists(payload_path): os.remove(payload_path)
            if os.path.exists(wrapper_path): os.remove(wrapper_path)
            return output_text
        else:
            result = subprocess.run(script, shell=True, capture_output=True, text=True)
            output = result.stdout + result.stderr
            if not output.strip():
                return "(Command executed successfully but returned no text output.)"
            return output
    except Exception as e:
        print(f"Execution Error: {e}")
        return str(e)

class ExecutionHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-type")
        self.end_headers()

    def do_GET(self):
        if self.path == '/browsers':
            browsers = get_installed_browsers()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"browsers": browsers}).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == '/execute':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                script = data.get('script', '')
                expected_process = data.get('expected_process', '')
                
                # Execute synchronously and capture the terminal output!
                output = execute_script(script)
                
                # Validation Phase
                validation_status = True
                if expected_process:
                    print(f"Validating process started: {expected_process}...")
                    time.sleep(2.0) # Wait for it to launch
                    validation_status = verify_process(expected_process)
                    print(f"Validation result: {'SUCCESS' if validation_status else 'FAILED'}")
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "executed", 
                    "output": output,
                    "validated": validation_status
                }).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

print(f"Cross-Platform Host Agent running natively on port {PORT}")
print("Listening for approved commands and registry scans from Docker...")

with socketserver.TCPServer(("127.0.0.1", PORT), ExecutionHandler) as httpd:
    httpd.serve_forever()
