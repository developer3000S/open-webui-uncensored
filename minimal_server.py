#!/usr/bin/env python3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Основные эндпоинты
@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/v1/models")
def list_models():
    return {"models": [{"id": "test-model", "object": "model", "created": 123456789}]}

@app.post("/api/v1/chat/completions")
def chat_completion():
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 123456789,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello! How can I help you?"
            },
            "finish_reason": "stop"
        }]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")