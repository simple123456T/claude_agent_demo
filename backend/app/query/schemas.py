from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.presentation.chart import ChartSpec
from app.semantic.models import QuerySpec


class MetricInfo(BaseModel):
    name: str
    label: str
    description: str | None = None
    unit: str | None = None
    aggregation: str
    synonyms: list[str] = []


class DimensionInfo(BaseModel):
    name: str
    label: str
    is_time: bool = False
    synonyms: list[str] = []


class DatasetInfo(BaseModel):
    name: str
    label: str
    description: str | None = None
    version: str
    metrics: list[MetricInfo]
    dimensions: list[DimensionInfo]


class DimensionValues(BaseModel):
    dimension: str
    values: list[str]
    truncated: bool


class AskRequest(BaseModel):
    """Either a natural-language question (needs the model) or a structured query."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str | None = Field(default=None, min_length=1, max_length=500)
    query: QuerySpec | None = None
    dataset: str | None = Field(default=None, max_length=63)

    @model_validator(mode="after")
    def exactly_one_input(self) -> Self:
        if (self.question is None) == (self.query is None):
            raise ValueError("Provide exactly one of 'question' or 'query'")
        return self


class ResultColumn(BaseModel):
    name: str
    label: str
    role: Literal["dimension", "metric"]
    unit: str | None = None


class Evidence(BaseModel):
    dataset: str
    dataset_label: str
    semantic_version: str
    source: Literal["natural_language", "structured"]
    sql: str
    row_count: int
    truncated: bool
    elapsed_ms: int
    filters: list[str]


class AskResponse(BaseModel):
    status: Literal["ok", "clarify", "unsupported"]
    message: str | None = None
    summary: str | None = None
    assumptions: list[str] = []
    query: QuerySpec | None = None
    columns: list[ResultColumn] = []
    rows: list[list[Any]] = []
    chart: ChartSpec | None = None
    evidence: Evidence | None = None
