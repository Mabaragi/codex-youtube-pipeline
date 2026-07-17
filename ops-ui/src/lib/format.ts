const KOREAN_DATE_TIME = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "short",
  timeStyle: "medium",
});
const KOREAN_NUMBER = new Intl.NumberFormat("ko-KR");

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : KOREAN_DATE_TIME.format(date);
}

export function formatNumber(value: number | null | undefined): string {
  return value == null ? "—" : KOREAN_NUMBER.format(value);
}

export function formatIdentifier(value: string | number | null | undefined): string {
  return value == null || value === "" ? "—" : String(value);
}
