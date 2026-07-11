from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from codex_sdk_cli.api.schemas.work import (
    CancelWorkItemRequest,
    RetryWorkItemRequest,
    WorkBatchDetailResponse,
    WorkflowRunDetailResponse,
    WorkItemDetailResponse,
    WorkItemListResponse,
    WorkItemResponse,
    work_batch_detail_response,
    work_item_detail_response,
    work_item_list_response,
    work_item_response,
    workflow_run_detail_response,
)
from codex_sdk_cli.api.use_case_dependencies.work import (
    CancelWorkItemUseCaseDep,
    GetWorkBatchUseCaseDep,
    GetWorkflowRunUseCaseDep,
    GetWorkItemUseCaseDep,
    ListWorkItemsUseCaseDep,
    RetryWorkItemUseCaseDep,
)
from codex_sdk_cli.application.work.ports import WorkItemQuery
from codex_sdk_cli.domains.work.models import WorkItemStatus

router = APIRouter()


@router.get("/work-batches/{batch_id}", response_model=WorkBatchDetailResponse)
async def get_work_batch(
    batch_id: Annotated[int, Path(ge=1)],
    use_case: GetWorkBatchUseCaseDep,
) -> WorkBatchDetailResponse:
    return work_batch_detail_response(await use_case.execute(batch_id))


@router.get("/workflows/{workflow_run_id}", response_model=WorkflowRunDetailResponse)
async def get_workflow_run(
    workflow_run_id: Annotated[int, Path(ge=1)],
    use_case: GetWorkflowRunUseCaseDep,
) -> WorkflowRunDetailResponse:
    return workflow_run_detail_response(await use_case.execute(workflow_run_id))


@router.get("/work-items", response_model=WorkItemListResponse)
async def list_work_items(
    use_case: ListWorkItemsUseCaseDep,
    task_type: Annotated[str | None, Query(alias="taskType", min_length=1)] = None,
    work_status: Annotated[WorkItemStatus | None, Query(alias="status")] = None,
    subject_type: Annotated[
        str | None, Query(alias="subjectType", min_length=1)
    ] = None,
    subject_id: Annotated[int | None, Query(alias="subjectId", ge=1)] = None,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> WorkItemListResponse:
    result = await use_case.execute(
        WorkItemQuery(
            task_type=task_type,
            status=work_status,
            subject_type=subject_type,
            subject_id=subject_id,
            cursor=cursor,
            limit=limit,
        )
    )
    return work_item_list_response(result)


@router.get("/work-items/{work_item_id}", response_model=WorkItemDetailResponse)
async def get_work_item(
    work_item_id: Annotated[int, Path(ge=1)],
    use_case: GetWorkItemUseCaseDep,
) -> WorkItemDetailResponse:
    return work_item_detail_response(await use_case.execute(work_item_id))


@router.post("/work-items/{work_item_id}/retry", response_model=WorkItemResponse)
async def retry_work_item(
    work_item_id: Annotated[int, Path(ge=1)],
    request: RetryWorkItemRequest,
    use_case: RetryWorkItemUseCaseDep,
) -> WorkItemResponse:
    return work_item_response(
        await use_case.execute(
            work_item_id,
            rerun_succeeded=request.rerun_succeeded,
        )
    )


@router.post("/work-items/{work_item_id}/cancel", response_model=WorkItemResponse)
async def cancel_work_item(
    work_item_id: Annotated[int, Path(ge=1)],
    request: CancelWorkItemRequest,
    use_case: CancelWorkItemUseCaseDep,
) -> WorkItemResponse:
    return work_item_response(
        await use_case.execute(work_item_id, reason=request.reason)
    )
