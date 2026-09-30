"use client";

import { useState } from "react";

import { ActionDialog } from "@/components/action-dialog";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { useAutomationStatus, useSetPublishingState } from "@/features/automation/api";
import { formatNumber } from "@/lib/format";

export function PublishingControl() {
  const status = useAutomationStatus();
  const mutation = useSetPublishingState();
  const [nextEnabled, setNextEnabled] = useState<boolean | null>(null);
  const publishing = status.data?.publishing;
  const enable = nextEnabled ?? (publishing ? !publishing.enabled : false);
  const label = enable ? "게시 켜기" : "게시 끄기";
  return (
    <Panel.Root>
      <Panel.Header>
        <Panel.HeadingGroup>
          <Panel.Title>게시 워커</Panel.Title>
          <Panel.Description>OFF에서도 콘텐츠 생성은 계속되고 게시 작업은 대기합니다.</Panel.Description>
        </Panel.HeadingGroup>
        <ActionDialog.Provider
          heading={label}
          description={enable
            ? "대기 중인 게시 작업을 이어받아 외부 저장소와 카탈로그에 게시합니다."
            : "새 게시 작업 수락을 멈춥니다. 실행 중인 게시 작업은 완료하고, 나머지는 대기합니다."}
          confirmLabel={label}
          reasonRequired
          onConfirm={async (reason) => { await mutation.mutateAsync({ enabled: enable, reason }); }}
        >
          <ActionDialog.Trigger><Button variant="outline" disabled={!publishing || status.isError} onClick={() => setNextEnabled(!publishing?.enabled)}>게시 설정</Button></ActionDialog.Trigger>
          <ActionDialog.Content><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content>
        </ActionDialog.Provider>
      </Panel.Header>
      <Panel.Body>
        <p role="status" className="ops-number text-sm">
          {publishing
            ? `게시 ${publishing.enabled ? "ON" : "OFF"} · 대기 ${formatNumber(publishing.pendingCount)} · 실행 ${formatNumber(publishing.runningCount)}`
            : "게시 상태를 불러오는 중…"}
        </p>
        {publishing?.reason ? <p className="mt-1 break-words text-xs text-[var(--muted)]">{publishing.reason}</p> : null}
        {status.isError ? <p role="alert" className="mt-1 text-sm text-[var(--danger)]">게시 상태 조회에 실패했습니다. 연결을 확인한 뒤 다시 시도하세요.</p> : null}
      </Panel.Body>
    </Panel.Root>
  );
}
