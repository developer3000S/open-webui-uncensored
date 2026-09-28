from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
import json

router = APIRouter()

class ClassifyRequest(BaseModel):
    text: str
    model: str | None = None

@router.post('/classify')
async def classify_endpoint(request: Request, payload: ClassifyRequest, user=Depends(lambda: None)):
    """Classify the provided text using an LLM.

    The model used defaults to the configured CLASSIFIER_MODEL.
    """
    # Retrieve classifier model from config or payload
    # Assuming Config.get is async method to fetch config value
    try:
        from open_webui.models.config import Config
        model_name = payload.model or await Config.get('classify.model')
    except Exception:
        model_name = payload.model or 'gpt-4o-mini'
    if not model_name:
        raise HTTPException(status_code=400, detail='Classifier model not configured')

    form_data = {
        'model': model_name,
        'messages': [{'role': 'user', 'content': payload.text}],
        'stream': False,
        'max_tokens': 50,
    }
    response = await request.app.state.CHAT_COMPLETION_HANDLER(request, form_data, user)
    try:
        body = response.body
        if isinstance(body, (bytes, bytearray)):
            data = json.loads(body)
        else:
            data = json.loads(str(body))
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail='Failed to parse classifier response')
    return {'label': content}
