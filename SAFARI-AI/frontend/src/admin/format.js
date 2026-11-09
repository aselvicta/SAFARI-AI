// Formatting helpers for the dashboard. Times show in East Africa Time, the parks' own clock.

const TIME_ZONE = "Africa/Dar_es_Salaam";
// Shown where a value is missing. (No dashes anywhere in the product copy.)
export const EMPTY = "n/a";

export function compact(value) {
  if (value === null || value === undefined) return EMPTY;
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function number(value, digits = 0) {
  if (value === null || value === undefined || value === "") return EMPTY;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

export function percent(value, digits = 0) {
  if (value === null || value === undefined) return EMPTY;
  return `${(value * 100).toFixed(digits)}%`;
}

export function ms(value) {
  if (value === null || value === undefined) return EMPTY;
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export function tzs(value) {
  if (value === null || value === undefined) return EMPTY;
  return `TZS ${number(value)}`;
}

export function bytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function formatDay(value, long = false) {
  if (!value) return "";
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("en-GB", long ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" }).format(date);
}

export function dateTime(value) {
  if (!value) return EMPTY;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE }).format(date);
}

export function ago(value) {
  if (!value) return "never";
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (!Number.isFinite(seconds)) return String(value);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return EMPTY;
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export function label(value) {
  if (!value) return EMPTY;
  return String(value).replace(/_/g, " ").replace(/^\w/, (first) => first.toUpperCase());
}
