from enum import StrEnum

from pydantic import Field

from app.semantic.models import Identifier, StrictModel


class Aggregation(StrEnum):
    SUM = "sum"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class ColumnDefinition(StrictModel):
    name: Identifier


class MetricDefinition(StrictModel):
    name: Identifier
    aggregation: Aggregation
    column: Identifier | None = None

    def source_required(self) -> bool:
        return self.aggregation != Aggregation.COUNT or self.column is not None


class DatasetDefinition(StrictModel):
    """Trusted, versioned semantic metadata supplied by a data steward."""

    name: Identifier
    version: str = Field(min_length=1, max_length=64)
    table: Identifier
    schema_name: Identifier | None = None
    columns: dict[Identifier, ColumnDefinition] = Field(min_length=1)
    dimensions: dict[Identifier, Identifier] = Field(default_factory=dict)
    metrics: dict[Identifier, MetricDefinition] = Field(default_factory=dict)

    def physical_column(self, semantic_name: str) -> str:
        if semantic_name in self.dimensions:
            return self.dimensions[semantic_name]
        return semantic_name


class SemanticRegistry:
    def __init__(self) -> None:
        self._datasets: dict[str, DatasetDefinition] = {}

    def register(self, dataset: DatasetDefinition) -> None:
        if dataset.name in self._datasets:
            raise ValueError(f"Dataset already registered: {dataset.name}")
        self._validate_dataset(dataset)
        self._datasets[dataset.name] = dataset

    def get(self, name: str) -> DatasetDefinition:
        try:
            return self._datasets[name]
        except KeyError as exc:
            raise KeyError(f"Unknown dataset: {name}") from exc

    @staticmethod
    def _validate_dataset(dataset: DatasetDefinition) -> None:
        for column_name, column in dataset.columns.items():
            if column.name != column_name:
                raise ValueError("Column definition keys must match column names")
        for dimension, column in dataset.dimensions.items():
            if column not in dataset.columns:
                raise ValueError(f"Dimension {dimension} references unknown column {column}")
        for metric_name, metric in dataset.metrics.items():
            if metric.name != metric_name:
                raise ValueError("Metric definition keys must match metric names")
            if metric.source_required() and metric.column not in dataset.columns:
                raise ValueError(f"Metric {metric_name} references an unknown column")
