from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,62}$"),
]
Scalar = str | int | float | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FilterOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"


class Filter(StrictModel):
    field: Identifier
    operator: FilterOperator
    values: list[Scalar] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        null_operators = {FilterOperator.IS_NULL, FilterOperator.NOT_NULL}
        if self.operator in null_operators and self.values:
            raise ValueError("Null filters do not accept values")
        if self.operator in {FilterOperator.IN, FilterOperator.NOT_IN} and not self.values:
            raise ValueError("IN filters require at least one value")
        if self.operator not in null_operators | {FilterOperator.IN, FilterOperator.NOT_IN}:
            if len(self.values) != 1:
                raise ValueError("This filter requires exactly one value")
        return self


class MetricRef(StrictModel):
    name: Identifier


class DimensionRef(StrictModel):
    name: Identifier


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class OrderBy(StrictModel):
    field: Identifier
    direction: SortDirection = SortDirection.ASC


class QuerySpec(StrictModel):
    """Untrusted model output. It contains no raw SQL or expression strings."""

    dataset: Identifier
    metrics: list[MetricRef] = Field(default_factory=list, max_length=20)
    dimensions: list[DimensionRef] = Field(default_factory=list, max_length=20)
    filters: list[Filter] = Field(default_factory=list, max_length=50)
    order_by: list[OrderBy] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=500, ge=1, le=500)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if not self.metrics and not self.dimensions:
            raise ValueError("At least one metric or dimension is required")
        if len({metric.name for metric in self.metrics}) != len(self.metrics):
            raise ValueError("Duplicate metrics are not allowed")
        if len({dimension.name for dimension in self.dimensions}) != len(self.dimensions):
            raise ValueError("Duplicate dimensions are not allowed")
        return self
