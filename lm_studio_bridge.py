import json
import urllib.request
import urllib.error
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ==================== CONFIGURATIONS ====================
OLLAMA_DEFAULT_PORT = 11434
LM_STUDIO_URL = "http://127.0.0.1:1234"
LM_API_TOKEN = "YOUR_LM_STUDIO_API_KEY_HERE" 
GLOBAL_TIMEOUT = 3600 
# ========================================================

def fetch_lm_studio_models():
    """Fetches all models available in LM Studio for ComfyUI's dropdown."""
    try:
        req = urllib.request.Request(f"{LM_STUDIO_URL}/v1/models", method='GET')
        req.add_header('Authorization', f'Bearer {LM_API_TOKEN}')
        with urllib.request.urlopen(req, timeout=10) as res:
            lm_data = json.loads(res.read().decode('utf-8'))
            models = lm_data.get("data", [])
            if models:
                return [{"name": m["id"], "model": m["id"]} for m in models]
    except Exception as e:
        print(f"[BRIDGE] Warning: Could not fetch models list from LM Studio: {e}")
    return [{"name": "lm-studio-model", "model": "lm-studio-model"}]

class UniversalStreamingProxy(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass 

    def do_GET(self):
        if self.path == '/api/tags':
            ollama_models = fetch_lm_studio_models()
            response_data = {"models": ollama_models}
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))

    def do_POST(self):
        if self.path in ['/api/generate', '/api/chat', '/api/generate/']:
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                
                # 1. EXTRACT PROMPTS AND DISABLE THINKING IN SYSTEM PROMPT
                raw_system = body.get("system", "")
                no_think_directive = "Respond directly. Do NOT output any reasoning, analysis, or thinking steps."
                system_prompt = f"{no_think_directive}\n\n{raw_system}" if raw_system else no_think_directive
                
                raw_prompt = body.get("prompt", "") or body.get("messages", [{}])[-1].get("content", "")
                
                requested_model = body.get("model", "")
                if not requested_model or requested_model == "lm-studio-model":
                    available = fetch_lm_studio_models()
                    requested_model = available[0]["model"]
                
                options = body.get("options", {})
                temp = options.get("temperature", 0.3)
                max_tokens = options.get("num_predict", 1024)
                if max_tokens <= 0:
                    max_tokens = 1024
                
                stop_seq = options.get("stop", None)

                print(f"[BRIDGE] Executing request for model: '{requested_model}' (Thinking Disabled)")

                # 2. ATTEMPT 1: Standard System + User Role with Thinking Disabled in Payload
                messages = []
                messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": raw_prompt})
                
                payload = {
                    "model": requested_model,
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": max_tokens,
                    "reasoning_effort": "none",               # Disables thinking mode via API
                    "chat_template_kwargs": {"thinking": False}, # Disables llama.cpp thinking pass
                    "stream": False 
                }
                if stop_seq:
                    payload["stop"] = stop_seq

                full_content = ""
                try:
                    req = urllib.request.Request(f"{LM_STUDIO_URL}/v1/chat/completions", data=json.dumps(payload).encode('utf-8'), method='POST')
                    req.add_header('Content-Type', 'application/json')
                    req.add_header('Authorization', f'Bearer {LM_API_TOKEN}')
                    
                    with urllib.request.urlopen(req, timeout=GLOBAL_TIMEOUT) as response:
                        lm_response = json.loads(response.read().decode('utf-8'))
                        msg = lm_response['choices'][0]['message']
                        full_content = msg.get('content', '') or ''
                except urllib.error.HTTPError as http_err:
                    print(f"[BRIDGE] Standard role request failed ({http_err.code}), attempting merged fallback...")

                # 3. ATTEMPT 2: Fallback for System-Role Sensitive Models
                if not full_content.strip():
                    merged_content = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER TASK:\n{raw_prompt}"
                    fallback_payload = {
                        "model": requested_model,
                        "messages": [{"role": "user", "content": merged_content}],
                        "temperature": temp,
                        "max_tokens": max_tokens,
                        "reasoning_effort": "none",
                        "chat_template_kwargs": {"thinking": False},
                        "stream": False
                    }
                    if stop_seq:
                        fallback_payload["stop"] = stop_seq

                    req_fb = urllib.request.Request(f"{LM_STUDIO_URL}/v1/chat/completions", data=json.dumps(fallback_payload).encode('utf-8'), method='POST')
                    req_fb.add_header('Content-Type', 'application/json')
                    req_fb.add_header('Authorization', f'Bearer {LM_API_TOKEN}')

                    with urllib.request.urlopen(req_fb, timeout=GLOBAL_TIMEOUT) as response_fb:
                        lm_response_fb = json.loads(response_fb.read().decode('utf-8'))
                        msg_fb = lm_response_fb['choices'][0]['message']
                        full_content = msg_fb.get('content', '') or ''

                print(f"[BRIDGE] Success! Returned {len(full_content.strip())} characters.")

                final_obj = {
                    "model": requested_model,
                    "done": True,
                    "response": full_content.strip()
                }
                
                resp_bytes = json.dumps(final_obj).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
                self.wfile.flush()
                    
            except Exception as e:
                print(f"!!! Error in do_POST: {e}")
                self.send_error(500, str(e))

if __name__ == '__main__':
    socket.setdefaulttimeout(GLOBAL_TIMEOUT)
    server = ThreadingHTTPServer(('127.0.0.1', OLLAMA_DEFAULT_PORT), UniversalStreamingProxy)
    print(f"Universal API Bridge Ready on {OLLAMA_DEFAULT_PORT}")
    server.serve_forever()
