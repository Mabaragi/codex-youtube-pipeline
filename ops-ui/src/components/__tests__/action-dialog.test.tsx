import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ActionDialog } from "@/components/action-dialog";
import { Button } from "@/components/ui/button";

it("대상 재입력과 운영 사유를 모두 검증하고 완료 후 trigger로 focus를 돌려준다", async () => {
  const confirm = vi.fn(async () => undefined);
  render(<ActionDialog.Provider heading="채널 삭제" description="대상 확인" confirmLabel="삭제" confirmationValue="42" reasonRequired tone="danger" onConfirm={confirm}><ActionDialog.Trigger><Button>삭제 열기</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ConfirmationField /><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider>);
  const trigger = screen.getByRole("button", { name: "삭제 열기" });
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "삭제" }));
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("textbox", { name: /확인 값/ }), { target: { value: "42" } });
  fireEvent.change(screen.getByRole("textbox", { name: /작업 사유/ }), { target: { value: "중복 채널 정리" } });
  fireEvent.click(screen.getByRole("button", { name: "삭제" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledWith("중복 채널 정리"));
  await waitFor(() => expect(document.activeElement).toBe(trigger));
});

it("Escape로 닫아도 trigger focus를 복원한다", async () => {
  render(<ActionDialog.Provider heading="작업 확인" description="설명" confirmLabel="실행" onConfirm={async () => undefined}><ActionDialog.Trigger><Button>열기</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider>);
  const trigger = screen.getByRole("button", { name: "열기" });
  fireEvent.click(trigger);
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(document.activeElement).toBe(trigger));
});
