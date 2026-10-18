from datetime import datetime
from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    id: int
    filename: str
    doc_type: str | None = None
    status: str
    file_url: str
    is_golden: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)