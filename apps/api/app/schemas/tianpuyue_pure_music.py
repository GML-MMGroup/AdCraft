from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class TianpuyueInstrumentalModelSelection(BaseModel):
    model: str
    duration_limit_seconds: int


class TianpuyueInstrumentalGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    model: str = Field(min_length=1)
    callback_url: str | None = None


class TianpuyueInstrumentalGenerateData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_ids: list[str] = Field(default_factory=list)


class TianpuyueInstrumentalGenerateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: StrictInt
    message: str
    request_id: str | None = None
    data: TianpuyueInstrumentalGenerateData | None = None


class TianpuyueInstrumentalQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[str] = Field(min_length=1)


class TianpuyueInstrumentalRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_id: str
    status: str | None = None
    audio_hi_status: str | None = None
    event: str | None = None
    model: str | None = None
    title: str | None = None
    style: str | None = None
    prompt: str | None = None
    duration: float | None = None
    audio_url: str | None = None
    audio_hi_url: str | None = None
    created_at: int | None = None
    finished_at: int | None = None


class TianpuyueInstrumentalQueryData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instrumentals: list[TianpuyueInstrumentalRecord] = Field(default_factory=list)


class TianpuyueInstrumentalQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: StrictInt
    message: str
    request_id: str | None = None
    data: TianpuyueInstrumentalQueryData | None = None


class TianpuyueInstrumentalCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instrumentals: list[TianpuyueInstrumentalRecord]
