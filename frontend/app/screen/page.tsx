"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ConditionForm from "./conditions";
import FavoritesPanel from "./favorites";
import type {
  ApplyResult,
  Favorite,
  FieldSpec,
  FilterSpec,
  RunResult,
  SpecStatus,
  SyncStatus,
} from "./types";
import { fmtCell, isFieldSpec } from "./types";
import { getJson, postJson } from "../api";

const COLUMN_LABELS: Record<string, string> = {
  code: "代码",
  name: "名称",
  rank: "#",
  is_favorite: "自选",
  pe_ttm: "PE(TTM)",
  pn: "PB",
  turnover: "成交额",
  ltsz: "流通市值",
  zsz: "总市值",
  hsl: "换手率",
  lb: "量比",
  zdf_y: "年初至今",
  zdf_d20: "近20日",
  zdf_d60: "近60日",
  zljlr: "主力净流入",
  eps: "每股收益",
  cfps: "每股现金流",
  revenue_yoy: "营收同比",
  net_profit_yoy: "净利润同比",
  net_profit: "净利润",
  roe: "ROE",
  gross_margin: "毛利率",
  industry: "行业",
  list_date: "上市日期",
};

const SORTABLE = [
  "net_profit_yoy",
  "revenue_yoy",
  "roe",
  "gross_margin",
  "pe_ttm",
  "pn",
  "turnover",
  "ltsz",
  "hsl",
  "zdf_y",
  "zdf_d20",
  "zljr",
  "eps",
];

export default function ScreenPage() {
  const [fields, setFields] = useState<FieldSpec[]>([]);
  const [status, setStatus] = useState<SpecStatus | null>(null);
  const [spec, setSpec] = useState<FilterSpec>({ conditions: [], sort_by: "net_profit_yoy", top: 100 });
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [result, setResult] = useState<RunResult | null>(null);
  const [nl, setNl] = useState("");
  const [busy, setBusy] = useState<"parse" | "run" | "apply" | null>(null);
  const [msg, setMsg] = useState("");
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const pollRef = useRef<number | null>(null);

  const loadFavorites = useCallback(() => {
    getJson<Favorite[]>("/api/favorites").then(setFavorites).catch(() => setFavorites([]));
  }, []);

  useEffect(() => {
    getJson<unknown>("/api/screener/fields")
      .then((raw) => {
        const list = Array.isArray(raw) ? raw.filter(isFieldSpec) : [];
        setFields(list);
      })
      .catch(() => setMsg("无法连接后端 API"));
    getJson<SpecStatus>("/api/screener/status").then(setStatus).catch(() => setStatus(null));
    loadFavorites();
  }, [loadFavorites]);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = window.setInterval(() => {
      getJson<SyncStatus>("/api/sync/status")
        .then((s) => {
          setSync(s);
          if (!s.running) {
            stopPolling();
            window.setTimeout(() => getJson<SyncStatus>("/api/sync/status").then(setSync).catch(() => {}), 1500);
          }
        })
        .catch(() => stopPolling());
    }, 2000);
  }, [stopPolling]);

  const onParse = async () => {
    if (nl.trim() === "") return;
    setBusy("parse");
    setMsg("");
    try {
      const parsed = await postJson<FilterSpec>("/api/screener/parse", { query: nl.trim() });
      setSpec(parsed);
      setMsg("已按你的描述回填条件，可直接修改后筛选。");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onRun = async () => {
    setBusy("run");
    setMsg("");
    try {
      const r = await postJson<RunResult>("/api/screener/run", spec);
      setResult(r);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onApply = async () => {
    if (!result || result.rows.length === 0) return;
    setBusy("apply");
    setMsg("");
    try {
      const res = await postJson<ApplyResult>("/api/screener/apply", {
        codes: result.rows.map((r) => r.code),
      });
      setMsg(`已写入池子 ${res.applied} 只，后台正在同步日线与财务数据…`);
      startPolling();
      getJson<SyncStatus>("/api/sync/status").then(setSync).catch(() => {});
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const syncPct = useMemo(() => {
    if (!sync || sync.total === 0) return 0;
    return Math.min(100, Math.round(((sync.done + sync.failed) / sync.total) * 100));
  }, [sync]);

  return (
    <main className="screen-page">
      <header className="screen-top">
        <a className="brand" href="/">
          个股分析
        </a>
        <nav className="screen-nav">
          <a href="/">分析</a>
          <a href="/screen" className="active">
            选股
          </a>
        </nav>
        <span className="screen-status">
          {status ? (status.llm_enabled ? "AI 解析可用" : "AI 解析未配置") : "连接中…"}
          {status?.snapshot_cached ? " · 行情已缓存" : ""}
        </span>
      </header>

      <div className="screen-cols">
        <section className="screen-left">
          <div className="card">
            <h3>自然语言筛选</h3>
            <textarea
              rows={3}
              placeholder="例如：市盈率小于 20，净利润同比超过 30%，属于半导体行业，取前 50 只"
              value={nl}
              disabled={status !== null && !status.llm_enabled}
              onChange={(e) => setNl(e.target.value)}
            />
            <div className="card-actions">
              <button
                className="primary"
                disabled={busy !== null || nl.trim() === "" || (status !== null && !status.llm_enabled)}
                onClick={() => void onParse()}
              >
                {busy === "parse" ? "解析中…" : "解析成条件"}
              </button>
              {status !== null && !status.llm_enabled && (
                <span className="hint">服务端未配置 GLM_API_KEY，请直接用下方表单填条件</span>
              )}
            </div>
          </div>

          <div className="card">
            <h3>筛选条件</h3>
            <ConditionForm
              fields={fields}
              value={spec.conditions}
              onChange={(conditions) => setSpec((s) => ({ ...s, conditions }))}
            />
          </div>

          <div className="card">
            <h3>排序与数量</h3>
            <div className="sort-row">
              <label>
                排序字段
                <select
                  value={spec.sort_by}
                  onChange={(e) => setSpec((s) => ({ ...s, sort_by: e.target.value }))}
                >
                  {SORTABLE.map((f) => (
                    <option key={f} value={f}>
                      {COLUMN_LABELS[f] ?? f}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                取前
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={spec.top}
                  onChange={(e) => setSpec((s) => ({ ...s, top: Math.max(1, Number(e.target.value) || 1) }))}
                />
                只
              </label>
              <button className="primary" disabled={busy !== null} onClick={() => void onRun()}>
                {busy === "run"
                  ? result?.cached || status?.snapshot_cached
                    ? "筛选中…"
                    : "拉取行情中，首次约 3-5 分钟…"
                  : "开始筛选"}
              </button>
            </div>
          </div>

          <div className="card">
            <h3>我的自选（强制保留在池内）</h3>
            <FavoritesPanel favorites={favorites} onChange={loadFavorites} onError={setMsg} onSynced={startPolling} />
          </div>
        </section>

        <section className="screen-right">
          {msg && <div className="card msg">{msg}</div>}

          {sync && (
            <div className="card">
              <h3>数据同步</h3>
              <div className="sync-bar">
                <div className="sync-fill" style={{ width: `${syncPct}%` }} />
              </div>
              <div className="sync-text">
                {sync.running
                  ? `同步中 ${sync.done}/${sync.total}${sync.current ? ` · 当前 ${sync.current}` : ""}${sync.failed ? ` · 失败 ${sync.failed}` : ""}`
                  : sync.finished_at
                    ? `同步完成 ${sync.done}/${sync.total}${sync.failed ? ` · 失败 ${sync.failed}` : ""}`
                    : "尚未开始同步"}
              </div>
            </div>
          )}

          <div className="card">
            <div className="result-head">
              <h3>
                筛选结果
                {result && (
                  <span className="result-meta">
                    命中 {result.total_matched} 只 · 用时 {result.elapsed_sec}s
                    {result.cached ? "（缓存）" : ""}
                  </span>
                )}
              </h3>
              {result && (
                <div className="result-summary">
                  <span className="tag in">将新入池 {result.next_in.length}</span>
                  <span className="tag out">将移出 {result.next_out.length}</span>
                  <span className="tag keep">自选保留 {result.kept_favorites.length}</span>
                  <button className="primary" disabled={busy !== null || result.rows.length === 0} onClick={() => void onApply()}>
                    {busy === "apply" ? "应用中…" : "应用到池子"}
                  </button>
                </div>
              )}
            </div>

            {!result && <div className="cond-hint">左侧设置条件后点「开始筛选」。筛选不会改动池子，点「应用到池子」后才写入。</div>}

            {result && result.rows.length === 0 && (
              <div className="cond-hint">没有股票满足当前条件，可放宽条件再试。</div>
            )}

            {result && result.rows.length > 0 && (
              <div className="table-wrap">
                <table className="screen-table">
                  <thead>
                    <tr>
                      {result.columns.map((c) => (
                        <th key={c}>{COLUMN_LABELS[c] ?? c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((r) => (
                      <tr key={r.code}>
                        {result.columns.map((c) => (
                          <td key={c} className={c === "name" || c === "industry" ? "" : "num"}>
                            {c === "is_favorite" ? (r.is_favorite ? "★" : "") : fmtCell(r[c])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}