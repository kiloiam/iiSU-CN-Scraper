"""轻量级 OpenAI 兼容客户端 — 使用 requests 替代 openai 包，节省 ~50 MB"""

import requests


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, data):
        choices = data.get("choices", [])
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, client):
        self._client = client

    def create(self, model, messages, temperature=0.1, max_tokens=300):
        url = f"{self._client.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._client.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
        return _Response(resp.json())


class _Chat:
    def __init__(self, client):
        self.completions = _Completions(client)


class LLMClient:
    """OpenAI 兼容的轻量客户端。用法:
        cl = LLMClient(base_url="https://api.deepseek.com/v1", api_key="sk-xxx")
        resp = cl.chat.completions.create(model="deepseek-chat", messages=[...])
        print(resp.choices[0].message.content)
    """

    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.chat = _Chat(self)
