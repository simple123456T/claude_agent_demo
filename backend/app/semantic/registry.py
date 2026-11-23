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
    label: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    unit: str | None = Field(default=None, max_length=20)

    def source_required(self) -> bool:
        return self.aggregation != Aggregation.COUNT or self.column is not None


class DatasetDefinition(StrictModel):
    """Trusted, versioned semantic metadata supplied by a data steward."""

    name: Identifier
    version: str = Field(min_length=1, max_length=64)
    table: Identifier
    schema_name: Identifier | None = None
    label: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    columns: dict[Identifier, ColumnDefinition] = Field(min_length=1)
    dimensions: dict[Identifier, Identifier] = Field(default_factory=dict)
    dimension_labels: dict[Identifier, str] = Field(default_factory=dict)
    time_dimensions: frozenset[Identifier] = Field(default_factory=frozenset)
    metrics: dict[Identifier, MetricDefinition] = Field(default_factory=dict)
    synonyms: dict[Identifier, list[str]] = Field(default_factory=dict)

    def physical_column(self, semantic_name: str) -> str:
        if semantic_name in self.dimensions:
            return self.dimensions[semantic_name]
        return semantic_name

    def metric_label(self, name: str) -> str:
        return self.metrics[name].label or name

    def dimension_label(self, name: str) -> str:
        return self.dimension_labels.get(name, name)

    def field_label(self, name: str) -> str:
        if name in self.metrics:
            return self.metric_label(name)
        return self.dimension_label(name)


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

    def all(self) -> list[DatasetDefinition]:
        return list(self._datasets.values())

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
        unknown_time = dataset.time_dimensions - set(dataset.dimensions)
        if unknown_time:
            raise ValueError(f"Time dimensions must be dimensions: {sorted(unknown_time)}")
        unknown_labels = set(dataset.dimension_labels) - set(dataset.dimensions)
        if unknown_labels:
            raise ValueError(f"Labels given for unknown dimensions: {sorted(unknown_labels)}")
        known = set(dataset.dimensions) | set(dataset.metrics)
        unknown_synonyms = set(dataset.synonyms) - known
        if unknown_synonyms:
            raise ValueError(f"Synonyms given for unknown fields: {sorted(unknown_synonyms)}")
