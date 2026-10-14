export function formatTime(value: number | string): string {
  const ms = typeof value === "number" ? value * 1000 : Date.parse(value);
  return new Date(ms).toLocaleString();
}

export function truncate(text: string, max = 80): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function round(n: number, places = 1): number {
  const f = 10 ** places;
  return Math.round(n * f) / f;
}
