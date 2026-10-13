"use client";

import { useMemo, useState } from "react";
import type { CondValue, Condition, FieldSpec } from "./types";
import { toNumberInput } from "./types";

type Props = {
  fields: FieldSpec[];
  value: Condition[];
  onChange: (next: Condition[]) => void;
};

const EMPTY: CondValue = "";

function defaultValue(spec: FieldSpec, op: string): CondValue {
  if (spec.kind === "enum") return [];
  if (op === "between") return [null, null] as unknown as number[];
  return EMPTY;
}

function specOf(fields: FieldSpec[], field: string): FieldSpec | undefined {
  return fields.find((f) => f.field === field);
}

function update(conds: Condition[], idx: number, patch: Partial<Condition>): Condition[] {
  return conds.map((c, i) => (i === idx ? { ...c, ...patch } : c));
}

export default function ConditionForm({ fields, value, onChange }: Props) {
  const [pendingField, setPendingField] = useState("");

  const used = new Set(value.map((c) => c.field));
  const unused = useMemo(() => fields.filter((f) => !used.has(f.field)), [fields, used]);

  const add = () => {
    const spec = specOf(fields, pendingField);
    if (!spec) return;
    const op = spec.ops[0];
    onChange([...value, { field: spec.field, op, value: defaultValue(spec, op) }]);
    setPendingField("");
  };

  const clear = () => {
    onChange([]);
    setPendingField("");
  };

  return (
    <div className="cond-form">
      <div className="cond-actions">
        <select value={pendingField} onChange={(e) => setPendingField(e.target.value)}>
          <option value="">选择筛选维度…</option>
          {unused.map((f) => (
            <option key={f.field} value={f.field}>
              {f.label}（{f.unit}）
            </option>
          ))}
        </select>
        <button type="button" onClick={add} disabled={!pendingField}>
          + 添加条件
        </button>
        <button type="button" onClick={clear} disabled={value.length === 0}>
          清除
        </button>
      </div>

      {value.length === 0 && <div className="cond-hint">未添加条件 = 不做筛选，仅按排序取前 N 只。</div>}

      {value.map((cond, idx) => {
        const spec = specOf(fields, cond.field);
        if (!spec) return null;
        return (
          <div className="cond-row" key={`${cond.field}-${idx}`}>
            <span className="cond-label">{spec.label}</span>
            <select
              value={cond.op}
              onChange={(e) => {
                const op = e.target.value;
                const keep = op === "between" ? Array.isArray(cond.value) : !Array.isArray(cond.value);
                onChange(
                  update(value, idx, {
                    op,
                    value: keep ? cond.value : defaultValue(spec, op),
                  }),
                );
              }}
            >
              {spec.ops.map((op) => (
                <option key={op} value={op}>
                  {spec.op_labels[op] ?? op}
                </option>
              ))}
            </select>

            {spec.kind === "number" && (
              <span className="cond-input">
                {cond.op === "between" ? (
                  <>
                    <input
                      type="number"
                      value={String((cond.value as number[])[0] ?? "")}
                      onChange={(e) => {
                        const arr = cond.value as number[];
                        const n = toNumberInput(e.target.value);
                        onChange(update(value, idx, { value: [n ?? 0, arr[1] ?? 0] }));
                      }}
                    />
                    <span className="tilde">~</span>
                    <input
                      type="number"
                      value={String((cond.value as number[])[1] ?? "")}
                      onChange={(e) => {
                        const arr = cond.value as number[];
                        const n = toNumberInput(e.target.value);
                        onChange(update(value, idx, { value: [arr[0] ?? 0, n ?? 0] }));
                      }}
                    />
                  </>
                ) : (
                  <input
                    type="number"
                    value={typeof cond.value === "number" ? String(cond.value) : ""}
                    onChange={(e) => {
                      const n = toNumberInput(e.target.value);
                      onChange(update(value, idx, { value: n ?? 0 }));
                    }}
                  />
                )}
                <span className="unit">{spec.unit}</span>
              </span>
            )}

            {spec.kind === "date" && (
              <input
                className="cond-input"
                type="date"
                value={typeof cond.value === "string" ? cond.value : ""}
                onChange={(e) => onChange(update(value, idx, { value: e.target.value }))}
              />
            )}

            {spec.kind === "enum" && (
              <select
                className="cond-input"
                multiple
                size={Math.min(4, Math.max(3, spec.options.length))}
                value={Array.isArray(cond.value) ? (cond.value as string[]) : []}
                onChange={(e) => {
                  const picked = Array.from(e.target.selectedOptions).map((o) => o.value);
                  onChange(update(value, idx, { value: picked }));
                }}
              >
                {spec.options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            )}

            <button type="button" className="cond-del" onClick={() => onChange(value.filter((_, i) => i !== idx))}>
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}