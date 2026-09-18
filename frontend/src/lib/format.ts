export function formatDateTime(value: string): string {
  const date = new Date(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}`;
}

export function formatDuration(value: number | null): string {
  if (value === null) {
    return "—";
  }
  if (value < 1_000) {
    return `${value} ms`;
  }
  return `${(value / 1_000).toFixed(value < 10_000 ? 2 : 1)} s`;
}
