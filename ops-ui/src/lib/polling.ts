const ACTIVE_STATES = new Set(["pending", "running", "waiting", "draining"]);

export function adaptiveRefetchInterval(values: readonly unknown[]): number | false {
  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    return false;
  }
  const active = values.some((value) => {
    if (typeof value === "string") return ACTIVE_STATES.has(value);
    if (value && typeof value === "object" && "status" in value) {
      return ACTIVE_STATES.has(String(value.status));
    }
    return false;
  });
  return active ? 5_000 : 15_000;
}
