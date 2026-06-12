from __future__ import annotations

from fastapi import APIRouter, Query

from .dependencies import (
    GetCodexAccountUseCaseDep,
    LoginCodexWithApiKeyUseCaseDep,
    LogoutCodexUseCaseDep,
    RunCodexPromptUseCaseDep,
)
from .schemas import (
    AccountResponse,
    ApiKeyLoginRequest,
    LoginResponse,
    LogoutResponse,
    RunRequest,
    RunResponse,
)

router = APIRouter()


@router.post("/runs", response_model=RunResponse)
async def run_codex_prompt(
    request: RunRequest,
    use_case: RunCodexPromptUseCaseDep,
) -> RunResponse:
    return await use_case.execute(request)


@router.get("/account", response_model=AccountResponse)
async def get_codex_account(
    use_case: GetCodexAccountUseCaseDep,
    refresh_token: bool = Query(default=False, alias="refreshToken"),
) -> AccountResponse:
    return await use_case.execute(refresh_token=refresh_token)


@router.post("/login/api-key", response_model=LoginResponse)
async def login_codex_with_api_key(
    request: ApiKeyLoginRequest,
    use_case: LoginCodexWithApiKeyUseCaseDep,
) -> LoginResponse:
    return await use_case.execute(request)


@router.post("/logout", response_model=LogoutResponse)
async def logout_codex(use_case: LogoutCodexUseCaseDep) -> LogoutResponse:
    return await use_case.execute()
