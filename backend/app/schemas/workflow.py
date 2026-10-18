from typing import Any
from pydantic import BaseModel, ConfigDict


class FieldSchema(BaseModel):
    key: str
    label: str
    type: str = "text"  # text, date, number


class DocTypeCreate(BaseModel):
    name: str
    fields_schema: list[FieldSchema]


class DocTypeResponse(BaseModel):
    id: int
    name: str
    fields_schema: list[dict[str, Any]]

    model_config = ConfigDict(from_attributes=True)


class SubmissionCreate(BaseModel):
    document_id: int
    assessor_id: str
    selected_doc_type: str | None = None
    data: dict[str, Any] = {}
    is_trash: bool = False
    duration_seconds: float = 0.0


class AdminResolveRequest(BaseModel):
    winning_submission_id: int | None = None
    winning_assessor_id: str | None = None
    doc_type: str | None = None
    final_data: dict[str, Any] = {}
    is_trash: bool = False


class CdnUrlsRequest(BaseModel):
    urls: list[str]


class OverlapUpdate(BaseModel):
    overlap_percent: int


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "assessor"  # "assessor", "admin", "superadmin"


class UserUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str