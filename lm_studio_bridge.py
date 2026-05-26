import json
import re
import urllib.request
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ==================== CONFIGURATIONS ====================
OLLAMA_DEFAULT_PORT = 11434
LM_STUDIO_URL = "http://127.0.0.1:1234"

# YOUR LM STUDIO API TOKEN
LM_API_TOKEN = "YOUR_LM_STUDIO_API_KEY_HERE" 

# TIMEOUT: 3600 seconds (1 hour) to survive deep reasoning
GLOBAL_TIMEOUT = 3600 
# ========================================================

class UniversalBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass 

    def do_GET(self):
        """Universal Model Sync: Fetches loaded models with Authorization."""
        if self.path == '/api/tags':
            try:
                req = urllib.request.Request(f"{LM_STUDIO_URL}/v1/models", method='GET')
                req.add_header('Authorization', f'Bearer {LM_API_TOKEN}')
                with urllib.request.urlopen(req, timeout=10) as res:
                    lm_data = json.loads(res.read().decode('utf-8'))
                
                ollama_models = []
                for m in lm_data.get("data", []):
                    m_id = m.get("id")
                    ollama_models.append({
                        "name": m_id, "model": m_id, "details": {"family": "llama"}
                    })
                
                if not ollama_models:
                    ollama_models = [{"name": "no-model-loaded", "model": "error", "details": {"family": "llama"}}]
                
                response_data = {"models": ollama_models}
            except Exception:
                response_data = {"models": [{"name": "bridge-connection-error", "model": "error", "details": {"family": "llama"}}]}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))

    def do_POST(self):
        """Universal Reasoning Stripper with Persistence."""
        if self.path in ['/api/generate', '/api/chat']:
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            prompt = body.get("prompt", "") or body.get("messages", [{}])[-1].get("content", "")
            model_name = body.get("model", "lm-studio-model")
            system_prompt = body.get("system", "")

            # Prevent Error Loops: Don't send previous error messages as prompts
            if "Bridge POST Error" in prompt or "HTTP Error" in prompt:
                final_output = "Error: Input contained a previous failure message. Check workflow logic."
            else:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": str(system_prompt).strip()})
                messages.append({"role": "user", "content": prompt})

                payload = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": body.get("options", {}).get("temperature", 0.7),
                    "stream": False
                }

                try:
                    req = urllib.request.Request(
                        f"{LM_STUDIO_URL}/v1/chat/completions",
                        data=json.dumps(payload).encode('utf-8'),
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {LM_API_TOKEN}',
                            'Connection': 'keep-alive'
                        },
                        method='POST'
                    )
                    
                    print(f"--- Model {model_name} is reasoning (Wait up to 1hr)... ---")
                    with urllib.request.urlopen(req, timeout=GLOBAL_TIMEOUT) as response:
                        lm_res = json.loads(response.read().decode('utf-8'))
                        raw_text = lm_res['choices'][0]['message']['content']
                        
                        # UNIVERSAL CLEANING
                        cleaned = re.sub(r"<(think|thought|reasoning)>.*?</\1>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
                        if "---" in cleaned: cleaned = cleaned.split("---")[-1]
                        
                        headers_regex = r"^(#+|\*\*+)\s*(Reasoning|Thought|Analysis|Verification|Process|Step-by-step).*?(\n|$)"
                        cleaned = re.sub(headers_regex, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
                        
                        anchors_regex = r"^(#+|\*\*+)?\s*(Final\s*Answer|Final\s*Output|Result|Output|Lyrics|Tags|Title|Songtitle)\s*(:|#+)?\s*"
                        cleaned = re.sub(anchors_regex, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
                        
                        final_output = re.sub(r"```[a-zA-Z]*\n|```", "", cleaned).strip()
                        print(f"--- Done! ---")
                        
                except Exception as e:
                    print(f"!!! BRIDGE ERROR: {e}")
                    final_output = f"Bridge POST Error: {str(e)}"

            ollama_response = {
                "model": model_name,
                "response": final_output,
                "message": {"role": "assistant", "content": final_output},
                "context": [1, 2, 3, 4, 5], 
                "done": True
            }

            try:
                response_bytes = json.dumps(ollama_response).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response_bytes)))
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                self.wfile.write(response_bytes)
            except BrokenPipeError:
                print("!!! ERROR: ComfyUI closed the connection before the bridge could send data.")

if __name__ == '__main__':
    socket.setdefaulttimeout(GLOBAL_TIMEOUT)
    # Using ThreadingHTTPServer to handle long-blocked connections correctly
    server = ThreadingHTTPServer(('127.0.0.1', OLLAMA_DEFAULT_PORT), UniversalBridgeHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    print(f"Universal API Bridge (Threading) active on port {OLLAMA_DEFAULT_PORT}...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
