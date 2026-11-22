from pydantic import Field

from app.semantic.models import Filter, Identifier, StrictModel


class AccessPolicy(StrictModel):
    """Trusted policy resolved on the server; never supplied by the model."""

    workspace_id: Identifier
    allowed_columns: frozenset[Identifier] = Field(default_factory=frozenset)
    row_filters: list[Filter] = Field(default_factory=list, max_length=50)
    max_rows: int = Field(default=500, ge=1, le=500)

    def allows(self, column: str) -> bool:
        return column in self.allowed_columns
