import sqlglot
from sqlglot import expressions as exp


class SQLSafetyError(ValueError):
    """Generated SQL failed the independent read-only safety check."""


_FORBIDDEN_NODE_NAMES = (
    "Alter",
    "Create",
    "Delete",
    "Drop",
    "Insert",
    "Update",
    "Merge",
    "Command",
    "Transaction",
    "Commit",
    "Rollback",
    "Grant",
    "Revoke",
    "TruncateTable",
    "Into",
    "Lock",
)
_FORBIDDEN_NODES = tuple(
    node_type
    for name in _FORBIDDEN_NODE_NAMES
    if isinstance(node_type := getattr(exp, name, None), type)
)
_SYSTEM_SCHEMAS = {
    "information_schema",
    "pg_catalog",
    "mysql",
    "performance_schema",
    "sys",
    "system",
}


def validate_read_only(sql: str, dialect: str, max_rows: int = 500) -> exp.Query:
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise SQLSafetyError("SQL parsing failed") from exc

    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise SQLSafetyError("Exactly one read-only query is required")
    statement = statements[0]

    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SQLSafetyError(f"Forbidden SQL operation: {type(node).__name__}")
        if isinstance(node, exp.Anonymous):
            raise SQLSafetyError("Unapproved SQL functions are not allowed")
        if isinstance(node, exp.Table):
            if isinstance(node.this, exp.Func):
                raise SQLSafetyError("Table functions are not allowed")
            if node.db.lower() in _SYSTEM_SCHEMAS:
                raise SQLSafetyError("System schemas are not available to generated queries")

    limit = statement.args.get("limit")
    if limit is None:
        raise SQLSafetyError("A top-level LIMIT is required")
    literal = limit.expression
    if not isinstance(literal, exp.Literal) or not literal.is_number:
        raise SQLSafetyError("LIMIT must be a numeric literal")
    if int(literal.this) < 1 or int(literal.this) > max_rows:
        raise SQLSafetyError(f"LIMIT must be between 1 and {max_rows}")
    return statement
