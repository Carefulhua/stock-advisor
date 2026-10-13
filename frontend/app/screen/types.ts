import type { CellValue } from "../api";

export type FieldKind = "number" | "enum" | "date";

export type FieldSpec = {
  field: string;
  label: string;
  unit: string;
  kind: FieldKind;
  ops: string[];
  options: string[];
  op_labels: Record<string, string>;
};

export type CondValue = number | number[] | string | string[];

export type Condition = {
  field: string;
  op: string;
  value: CondValue;
};

export type FilterSpec = {
  conditions: Condition[];
  sort_by: string;
  top: number;
};

export type SpecStatus = {
  llm_enabled: boolean;
  snapshot_cached: boolean;
};

export type RunRow = Record<string, CellValue> & { code: string; name: string };

export type RunResult = {
  rows: RunRow[];
  columns: string[];
  next_in: string[];
  next_out: string[];
  kept_favorites: string[];
  total_matched: number;
  elapsed_sec: number;
  cached: boolean;
};

export type Favorite = {
  code: string;
  name: string;
  added_at: string;
};

export type SyncStatus = {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  current: string;
  started_at: string;
  finished_at: string;
  job_id: string;
};

export type AddResult = { added: number; skipped: number };
export type DeleteResult = { deleted: boolean };
export type ApplyResult = { applied: number; sync_job_id: string };

export function isFieldSpec(v: unknown): v is FieldSpec {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.field === "string" &&
    typeof o.label === "string" &&
    typeof o.kind === "string" &&
    Array.isArray(o.ops)
  );
}

export function toNumberInput(v: string): number | null {
  const t = v.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

const YI = 1e8;
const WAN = 1e4;

export function fmtCell(v: CellValue): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "是" : "否";
  // 后端 pandas to_json 把上市日期序列化成 ISO 时间戳，表格只需日期部分
  if (typeof v === "string") return /^\d{4}-\d{2}-\d{2}T/.test(v) ? v.slice(0, 10) : v;
  if (!Number.isFinite(v)) return String(v);
  const abs = Math.abs(v);
  if (abs >= YI) return `${(v / YI).toFixed(2)}亿`;
  if (abs >= WAN) return `${(v / WAN).toFixed(2)}万`;
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}