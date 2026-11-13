from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

class RegisterDevice(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model_id: str = Field(default="qwen3-0.6b", min_length=1, max_length=100)

class IssueKey(BaseModel):
    device_id: str
    label: str = Field(default="default", max_length=120)

class ChatMessage(BaseModel):
    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1)

class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    max_tokens: int = Field(default=256, ge=1, le=32768)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    stream: bool = False
    model_config = ConfigDict(extra='forbid')
