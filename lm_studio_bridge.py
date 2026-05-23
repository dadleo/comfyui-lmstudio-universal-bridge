import json
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==================== CONFIGURATIONS ====================
OLLAMA_DEFAULT_PORT = 11434
LM_STUDIO_URL = "http://127.0.0.1:1234"

# PASTE YOUR ACTUAL LM STUDIO API TOKEN HERE
LM_API_TOKEN = "YOUR_LM_STUDIO_API_KEY_HERE" 
# ========================================================

class LMStudioProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Keep terminal output clean

    def do_GET(self):
        if self.path == '/api/tags':
            try:
                req = urllib.request.Request(
                    f"{LM_STUDIO_URL}/v1/models", 
                    headers={'Authorization': f'Bearer {LM_API_TOKEN}'},
                    method='GET'
                )
                with urllib.request.urlopen(req) as res:
                    lm_data = json.loads(res.read().decode('utf-8'))
                
                ollama_models = []
                for m in lm_data.get("data", []):
                    ollama_models.append({
                        "name": m["id"], 
                        "model": m["id"],
                        "details": {"family": "llama"}
                    })
                
                if not ollama_models:
                    ollama_models = [{"name": "lm-studio-model", "model": "lm-studio-model", "details": {"family": "llama"}}]
                
                response_data = {"models": ollama_models}
                
            except Exception as e:
                response_data = {"models": [{"name": "lm-studio-model", "model": "lm-studio-model", "details": {"family": "llama"}}]}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))

    def do_POST(self):
        if self.path in ['/api/generate', '/api/chat']:
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            # Extract standard values from the comfyui-ollama node payload
            prompt = body.get("prompt", "") or body.get("messages", [{}])[-1].get("content", "")
            model_name = body.get("model", "lm-studio-model")
            
            # CRITICAL FIX: Intercept the hidden ComfyUI "system" prompt key from Node 334
            workflow_system_prompt = body.get("system", "")

            # Construct the formal array structure required by the LM Studio completions engine
            messages = []
            
            if workflow_system_prompt:
                # Inject the hidden system constraints into the primary execution role block
                messages.append({"role": "system", "content": str(workflow_system_prompt).strip()})
            else:
                # Hard fallback baseline rule if the payload transmission fails
                messages.append({
                    "role": "system", 
                    "content": "Start your response immediately with 'Title:'. Do not include any introductory conversation or explanations."
                })

            # Append the user parameters from the canvas text prompt box
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
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {LM_API_TOKEN}'
                    },
                    method='POST'
                )
                
                with urllib.request.urlopen(req, timeout=600) as response:
                    lm_response = json.loads(response.read().decode('utf-8'))
                    full_text = lm_response['choices'][0]['message']['content']
                    
            except Exception as e:
                full_text = "Title: Alternative Rock Ballad\n[Genre: Alternative Rock, Indie, 136 BPM]\n[Intro]\n🎵 🎵 🎵"

            # Post-generation layout cleaning to shield Node 150 against stray leading carriage returns
            final_output = str(full_text).strip()
            
            # If the model still attempts an accidental introduction sentence, strip it down to the target starting anchor
            if "title:" in final_output.lower() and not final_output.lower().startswith("title:"):
                title_index = final_output.lower().find("title:")
                final_output = final_output[title_index:]

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
            self.wfile.flush()

if __name__ == '__main__':
    print(f"Starting API Payload Key-Mapping Bridge on port {OLLAMA_DEFAULT_PORT}...")
    server = HTTPServer(('127.0.0.1', OLLAMA_DEFAULT_PORT), LMStudioProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down gateway bridge cleanly.")
        server.server_close()