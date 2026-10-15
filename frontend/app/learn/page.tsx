"use client";

import { useEffect, useState } from "react";
import { getJson, postJson } from "../api";

type ReportItem = { code: string; name: string; updated_at: string };
type LoadedReport = ReportItem & { content: string };

type ViewState =
  | { kind: "idle" }
  | { kind: "loading"; code: string }
  | { kind: "ready"; report: LoadedReport }
  | { kind: "missing"; code: string }
  | { kind: "empty"; report: ReportItem }
  | { kind: "error"; message: string };

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function LearnPage() {
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [code, setCode] = useState("");
  const [view, setView] = useState<ViewState>({ kind: "idle" });
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState("");

  useEffect(() => {
    loadReports();
  }, []);

  async function loadReports() {
    try {
      const data = await getJson<ReportItem[]>("/api/reports");
      setReports(data || []);
    } catch (e) {
      console.error("load reports error:", e);
    }
  }

  async function openReport(code: string) {
    setView({ kind: "loading", code });
    try {
      const r = await getJson<LoadedReport>(`/api/report/${code}`);
      const content = (r.content ?? "").trim();
      if (!content) {
        setView({ kind: "empty", report: r });
      } else {
        setView({ kind: "ready", report: { ...r, content } });
      }
    } catch (e) {
      const message = errorText(e);
      if (message.includes("404")) {
        setView({ kind: "missing", code });
      } else {
        setView({ kind: "error", message });
      }
    }
  }

  async function handleGenerate() {
    const target = code.trim();
    if (!target) {
      setGenError("请先填写股票代码");
      return;
    }
    setGenerating(true);
    setGenError("");
    try {
      await postJson(`/api/report/${target}/generate`, { code: target });
      await loadReports();
      await openReport(target);
    } catch (e) {
      setGenError(errorText(e));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <main>
      <div className="topbar">
        <span className="brand">个股分析</span>
        <nav className="screen-nav">
          <a href="/">分析</a>
          <a href="/screen">选股</a>
          <a href="/learn" className="active">
            学习
          </a>
        </nav>
      </div>

      <div className="learn-page">
        <h1>个股分析报告</h1>

        <div className="report-list">
          <h3>报告列表</h3>
          {reports.length === 0 ? (
            <div className="muted">暂无报告，填写股票代码后点击「生成报告」创建</div>
          ) : (
            <ul>
              {reports.map((r) => (
                <li key={r.code} onClick={() => openReport(r.code)}>
                  <span>
                    {r.code} - {r.name || r.code}
                  </span>
                  <span className="muted">{r.updated_at}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="report-gen">
          <input
            placeholder="股票代码，如 600519"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <button className="ai-toggle" disabled={generating} onClick={handleGenerate}>
            {generating ? "生成中…" : "生成报告"}
          </button>
          {genError && <div className="chat-error">{genError}</div>}
        </div>

        {view.kind === "loading" && <div className="muted">正在加载 {view.code} 的报告…</div>}
        {view.kind === "missing" && (
          <div className="muted">{view.code} 尚未生成报告，可填写代码后点击「生成报告」</div>
        )}
        {view.kind === "empty" && (
          <div className="chat-error">
            {view.report.code} 的报告内容为空，请重新生成
          </div>
        )}
        {view.kind === "error" && <div className="chat-error">加载失败：{view.message}</div>}
        {view.kind === "ready" && (
          <div className="report-viewer">
            <h3>
              {view.report.code} - {view.report.name || view.report.code}
            </h3>
            <pre className="report-body">{view.report.content}</pre>
          </div>
        )}
      </div>
    </main>
  );
}
