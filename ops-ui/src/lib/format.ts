export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  return numberFormatter.format(value);
}

export function compactId(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  if (value.length <= 16) {
    return value;
  }
  return `${value.slice(0, 8)}...${value.slice(-5)}`;
}

const numberFormatter = new Intl.NumberFormat("en");
