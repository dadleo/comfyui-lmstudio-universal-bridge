import json
import re
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==================== CONFIGURATIONS ====================
OLLAMA_DEFAULT_PORT = 11434
LM_STUDIO_URL = "http://127.0.0.1:1234"
LM_API_TOKEN = "sk-lm-JPk02vWM:9SSkR4pq4RZhZD004U9y" 
# ========================================================

class LMStudioProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass 

    def do_GET(self):
        """Fetches the list of LOADED models from LM Studio for ComfyUI to see."""
        if self.path == '/api/tags':
            try:
                req = urllib.request.Request(
                    f"{LM_STUDIO_URL}/v1/models", 
                    headers={'Authorization': f'Bearer {LM_API_TOKEN}'},
                    method='GET'
                )
                with urllib.request.urlopen(req, timeout=5) as res:
                    lm_data = json.loads(res.read().decode('utf-8'))
                
                ollama_models = []
                for m in lm_data.get("data", []):
                    m_id = m["id"]
                    ollama_models.append({
                        "name": m_id, 
                        "model": m_id,
                        "details": {"family": "llama"}
                    })
                
                if not ollama_models:
                    ollama_models = [{"name": "lm-studio-model", "model": "lm-studio-model", "details": {"family": "llama"}}]
                
                response_data = {"models": ollama_models}
                print(f"--- Synced {len(ollama_models)} models from LM Studio ---")
                
            except Exception as e:
                print(f"!!! GET Error: {e}. Defaulting to generic name.")
                response_data = {"models": [{"name": "lm-studio-model", "model": "lm-studio-model", "details": {"family": "llama"}}]}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))

    def do_POST(self):
        """Handles the prompt and cleans the reasoning output."""
        if self.path in ['/api/generate', '/api/chat']:
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            prompt = body.get("prompt", "") or body.get("messages", [{}])[-1].get("content", "")
            model_name = body.get("model", "lm-studio-model")
            workflow_system_prompt = body.get("system", "")

            messages = []
            if workflow_system_prompt:
                messages.append({"role": "system", "content": str(workflow_system_prompt).strip()})
            else:
                messages.append({"role": "system", "content": "You are a helpful assistant."})

            messages.append({"role": "user", "content": prompt})

            lm_payload = {
                "model": model_name,
                "messages": messages,
                "temperature": body.get("options", {}).get("temperature", 0.7),
                "stream": False
            }

            try:
                req = urllib.request.Request(
                    f"{LM_STUDIO_URL}/v1/chat/completions",
                    data=json.dumps(lm_payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {LM_API_TOKEN}'},
                    method='POST'
                )
                
                with urllib.request.urlopen(req, timeout=600) as response:
                    lm_response = json.loads(response.read().decode('utf-8'))
                    raw_text = lm_response['choices'][0]['message']['content']
                    
                    # --- UNIVERSAL CLEANING (Reasoning & Formatting) ---
                    # 1. Remove <think>...</think> tags (DeepSeek style)
                    cleaned_text = re.sub(r"<([a-zA-Z0-9_-]+)>.*?</\1>", "", raw_text, flags=re.DOTALL)
                    # 2. Remove **Reasoning** headers (Qwen/Llama style)
                    cleaned_text = re.sub(r"\*\*([rR]easoning|[tT]hought|[aA]nalysis|[pP]rocess)\*\*[:\s]*", "", cleaned_text)
                    # 3. Remove Markdown Code Blocks
                    cleaned_text = re.sub(r"```[a-zA-Z]*\n|```", "", cleaned_text, flags=re.IGNORECASE)
                    
                    final_output = cleaned_text.strip()
                    
            except Exception as e:
                print(f"!!! POST Error: {e}")
                final_output = prompt

            # FIX: Included context key required by ComfyUI-Ollama
            ollama_response = {
                "model": model_name,
                "response": final_output,
                "message": {"role": "assistant", "content": final_output},
                "context": [1, 2, 3, 4, 5], 
                "done": True
            }

            response_bytes = json.dumps(ollama_response).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)

if __name__ == '__main__':
    print(f"Starting API Bridge on port {OLLAMA_DEFAULT_PORT}...")
    server = HTTPServer(('127.0.0.1', OLLAMA_DEFAULT_PORT), LMStudioProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()