import http.server
import socketserver
import json
import subprocess

PORT = 8003

def execute_script(script):
    print(f"\n[DOCKER EXECUTOR] Running script:\n{script}\n")
    try:
        # Execute securely using bash in the linux container
        result = subprocess.run(['/bin/bash', '-c', script], capture_output=True, text=True)
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
            # Containers don't have host browsers
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"browsers": ["Containerized Browser"]}).encode())
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
                output = execute_script(script)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "executed", "output": output}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), ExecutionHandler) as httpd:
        print(f"Docker Executor running on port {PORT}")
        httpd.serve_forever()
