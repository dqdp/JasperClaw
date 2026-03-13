from pydantic import BaseModel


class SpeakRequest(BaseModel):
    input: str
    voice: str | None = None
