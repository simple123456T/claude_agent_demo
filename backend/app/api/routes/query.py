import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.audit.service import record_event, record_failure
from app.core.config import Settings, get_settings
from app.db.models import Workspace
from app.db.session import get_db, get_engine
from app.demo.dataset import build_demo_dataset
from app.execution.runner import QueryExecutionError, QueryTimeout
from app.execution.sql_guard import SQLSafetyError
from app.llm.client import ModelNotConfigured, ModelUnavailable, build_chat_client
from app.llm.planner import PlanFailed, Planner
from app.query import service
from app.query.schemas import AskRequest, AskResponse, DatasetInfo, DimensionValues
from app.semantic.compiler import QueryValidationError
from app.semantic.registry import SemanticRegistry
from app.workspaces.dependencies import WorkspaceContext, require_workspace_permission
from app.workspaces.permissions import Permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["query"])


@lru_cache
def get_registry() -> SemanticRegistry:
    registry = SemanticRegistry()
    registry.register(build_demo_dataset(get_settings().demo_schema))
    return registry


def get_query_engine() -> Engine:
    # Governed queries currently run on the same PostgreSQL as the control plane. A separate
    # read-only role per data source replaces this when real data sources are connected.
    return get_engine()


def get_planner_factory(settings: Settings = Depends(get_settings)) -> Callable[[], Planner]:
    """Planner is created on demand: structured queries must work with no model configured."""

    def create() -> Planner:
        try:
            return Planner(build_chat_client(settings))
        except ModelNotConfigured as exc:
            raise _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "model_not_configured",
                f"{exc}。可先使用「手动构建」查询。",
            ) from exc

    return create


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.get("/datasets", response_model=list[DatasetInfo])
def list_datasets(
    ctx: WorkspaceContext = Depends(require_workspace_permission(Permission.QUERY_RUN)),
    registry: SemanticRegistry = Depends(get_registry),
) -> list[DatasetInfo]:
    return service.catalog(registry, ctx.workspace.slug)


@router.get(
    "/datasets/{dataset_name}/dimensions/{dimension}/values", response_model=DimensionValues
)
def dimension_values(
    dataset_name: str,
    dimension: str,
    ctx: WorkspaceContext = Depends(require_workspace_permission(Permission.QUERY_RUN)),
    registry: SemanticRegistry = Depends(get_registry),
    engine: Engine = Depends(get_query_engine),
    settings: Settings = Depends(get_settings),
) -> DimensionValues:
    try:
        dataset = service.pick_dataset(registry, dataset_name)
    except service.DatasetNotFound as exc:
        raise _error(status.HTTP_404_NOT_FOUND, "dataset_not_found", "数据集不存在") from exc
    policy = service.resolve_policy(ctx.workspace.slug, dataset)
    if dimension not in service.visible_parts(dataset, policy).dimensions:
        raise _error(status.HTTP_404_NOT_FOUND, "dimension_not_found", "维度不存在")
    try:
        return service.fetch_dimension_values(
            engine, dataset, policy, dimension, timeout_ms=settings.query_timeout_ms
        )
    except QueryTimeout as exc:
        raise _error(status.HTTP_504_GATEWAY_TIMEOUT, "query_timeout", "查询超时") from exc
    except QueryExecutionError as exc:
        raise _error(status.HTTP_502_BAD_GATEWAY, "query_failed", "查询执行失败") from exc


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    ctx: WorkspaceContext = Depends(require_workspace_permission(Permission.QUERY_RUN)),
    registry: SemanticRegistry = Depends(get_registry),
    engine: Engine = Depends(get_query_engine),
    settings: Settings = Depends(get_settings),
    planner_factory: Callable[[], Planner] = Depends(get_planner_factory),
    db: Session = Depends(get_db),
) -> AskResponse:
    workspace: Workspace = ctx.workspace
    source: Literal["natural_language", "structured"] = (
        "natural_language" if body.question is not None else "structured"
    )
    question = (body.question or "")[:500] or None
    audit: dict[str, Any] = {
        "actor_user_id": ctx.user.id,
        "actor_subject": ctx.user.subject,
        "workspace_id": workspace.id,
        "target_type": "workspace",
        "target_id": str(workspace.id),
        "request_id": ctx.request_id,
    }

    def fail(status_code: int, code: str, message: str) -> HTTPException:
        """Audit the failure (in its own transaction) and build the client-facing error."""

        record_failure(
            db,
            action="query.run",
            details={"source": source, "error": code, "question": question},
            **audit,
        )
        return _error(status_code, code, message)

    requested = body.dataset or (body.query.dataset if body.query else None)
    try:
        dataset = service.pick_dataset(registry, requested)
    except service.DatasetNotFound as exc:
        raise fail(status.HTTP_404_NOT_FOUND, "dataset_not_found", "数据集不存在") from exc
    except service.AmbiguousDataset as exc:
        raise fail(
            422, "dataset_required", "请指定要查询的数据集"
        ) from exc
    policy = service.resolve_policy(workspace.slug, dataset)

    try:
        if body.query is not None:
            result = service.execute_spec(
                engine,
                dataset,
                policy,
                body.query,
                source="structured",
                assumptions=[],
                timeout_ms=settings.query_timeout_ms,
            )
        else:
            result = service.ask_natural_language(
                engine,
                planner_factory(),
                dataset,
                policy,
                body.question or "",
                timeout_ms=settings.query_timeout_ms,
            )
    except HTTPException as exc:  # e.g. model not configured
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        raise fail(
            exc.status_code, detail.get("code", "error"), detail.get("message", "请求失败")
        ) from exc
    except QueryValidationError as exc:
        raise fail(422, "invalid_query", str(exc)) from exc
    except PlanFailed as exc:
        raise fail(
            422,
            "plan_failed",
            "没能把问题转换成有效的查询，请换一种说法，或使用「手动构建」。",
        ) from exc
    except ModelUnavailable as exc:
        raise fail(
            status.HTTP_502_BAD_GATEWAY, "model_unavailable", f"模型服务不可用：{exc}"
        ) from exc
    except QueryTimeout as exc:
        raise fail(
            status.HTTP_504_GATEWAY_TIMEOUT, "query_timeout", "查询超时，请缩小范围后重试"
        ) from exc
    except QueryExecutionError as exc:
        raise fail(status.HTTP_502_BAD_GATEWAY, "query_failed", "查询执行失败") from exc
    except SQLSafetyError as exc:
        # Compiled SQL failed the independent check: a bug, not a user mistake.
        logger.error("Compiled SQL rejected by safety check: %s", exc)
        raise fail(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "内部错误") from exc

    evidence = result.evidence
    record_event(
        db,
        action="query.run",
        outcome="success",
        details={
            "source": source,
            "status": result.status,
            "question": question,
            "query": result.query.model_dump(mode="json") if result.query else None,
            "rows": evidence.row_count if evidence else None,
            "truncated": evidence.truncated if evidence else None,
            "elapsed_ms": evidence.elapsed_ms if evidence else None,
            "semantic_version": evidence.semantic_version if evidence else None,
        },
        **audit,
    )
    db.commit()
    return result
