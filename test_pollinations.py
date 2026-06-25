import urllib.request
import json

def test_pollinations():
    url = "https://text.pollinations.ai/"
    data = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Respond with JSON containing intent and slots."},
            {"role": "user", "content": "Open the google chrome browser please."}
        ],
        "model": "openai",
        "jsonMode": True
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            result = response.read().decode('utf-8')
            print("Response:", result)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_pollinations()
