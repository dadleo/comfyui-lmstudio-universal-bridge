import json
import re
import urllib.request
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==================== CONFIGURATIONS ====================
OLLAMA_DEFAULT_PORT = 11434
LM_STUDIO_URL = "http://127.0.0.1:1234"

# YOUR LM STUDIO API TOKEN
LM_API_TOKEN = "YOUR_LM_STUDIO_API_KEY_HERE" 

# TIMEOUT: 2400 seconds (40 minutes) for deep reasoning
GLOBAL_TIMEOUT = 2400 
# ========================================================

class UniversalBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Keep terminal clean

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
            except Exception as e:
                print(f"!!! GET ERROR: {e}")
                response_data = {"models": [{"name": "bridge-connection-error", "model": "error", "details": {"family": "llama"}}]}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))

    def do_POST(self):
        """Universal Reasoning Stripper with Strict Payload Handling."""
        if self.path in ['/api/generate', '/api/chat']:
            try:
                content_length = int(self.headers['Content-Length'])
                raw_body = self.rfile.read(content_length).decode('utf-8')
                body = json.loads(raw_body)
                
                prompt = body.get("prompt", "") or body.get("messages", [{}])[-1].get("content", "")
                model_name = body.get("model", "lm-studio-model")
                system_prompt = body.get("system", "")

                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": str(system_prompt).strip()})
                messages.append({"role": "user", "content": prompt})

                payload_dict = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": body.get("options", {}).get("temperature", 0.7),
                    "stream": False
                }
                
                encoded_payload = json.dumps(payload_dict).encode('utf-8')

                # Request to LM Studio
                req = urllib.request.Request(f"{LM_STUDIO_URL}/v1/chat/completions", data=encoded_payload, method='POST')
                req.add_header('Content-Type', 'application/json; charset=utf-8')
                req.add_header('Authorization', f'Bearer {LM_API_TOKEN}')
                req.add_header('Content-Length', str(len(encoded_payload)))
                req.add_header('Connection', 'keep-alive')
                
                print(f"--- Model {model_name}: Thinking... ---")
                
                with urllib.request.urlopen(req, timeout=GLOBAL_TIMEOUT) as response:
                    lm_res = json.loads(response.read().decode('utf-8'))
                    raw_text = lm_res['choices'][0]['message']['content']
                    
                    # UNIVERSAL REASONING STRIPPING
                    cleaned = re.sub(r"<(think|thought|reasoning)>.*?</\1>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
                    if "---" in cleaned:
                        cleaned = cleaned.split("---")[-1]
                    
                    headers_regex = r"^(#+|\*\*+)\s*(Reasoning|Thought|Analysis|Verification|Process|Step-by-step).*?(\n|$)"
                    cleaned = re.sub(headers_regex, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
                    
                    anchors_regex = r"^(#+|\*\*+)?\s*(Final\s*Answer|Final\s*Output|Result|Output|Lyrics|Tags|Title|Songtitle)\s*(:|#+)?\s*"
                    cleaned = re.sub(anchors_regex, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
                    
                    cleaned = re.sub(r"```[a-zA-Z]*\n|```", "", cleaned)
                    final_output = cleaned.strip()
                    print(f"--- Success: Sending result to ComfyUI ---")
                    
            except Exception as e:
                print(f"!!! BRIDGE POST ERROR: {e}")
                final_output = f"Bridge Error: {str(e)}"

            # Create Ollama-compatible response
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
            except Exception as e:
                print(f"!!! CLIENT DISCONNECT: ComfyUI closed the connection before bridge could finish: {e}")

if __name__ == '__main__':
    # Force system-level persistent timeout
    socket.setdefaulttimeout(GLOBAL_TIMEOUT)
    
    server_address = ('127.0.0.1', OLLAMA_DEFAULT_PORT)
    httpd = HTTPServer(server_address, UniversalBridgeHandler)
    
    # Enable Keep-Alive at socket level
    httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    
    print(f"Universal API Bridge active on port {OLLAMA_DEFAULT_PORT}...")
    print(f"Targeting LM Studio at {LM_STUDIO_URL}")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down bridge.")
        httpd.server_close()
