"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { postJson } from "./api";
import * as echarts from "echarts";
import ChatPanel from "./ChatPanel";
import { buildChartOption, IndicatorTab, MaKey, MaVisible, Row } from "./chartOption";
import { API } from "./api";

type Stock = { code: string; name: string; in_watchlist: boolean };
type WatchItem = { code: string; name: string; is_favorite: boolean };

const PERIODS = [
  { key: "day", label: "日K" },
  { key: "week", label: "周K" },
  { key: "month", label: "月K" },
  { key: "quarter", label: "季K" },
  { key: "year", label: "年K" },
] as const;
type PeriodKey = (typeof PERIODS)[number]["key"];

const TABS: { key: IndicatorTab; label: string }[] = [
  { key: "macd", label: "MACD" },
  { key: "kdj", label: "KDJ" },
  { key: "rsi", label: "RSI" },
];

const ALL_MA: MaVisible = { ma5: true, ma10: true, ma20: true, ma60: true };
const MA_BY_LABEL: Record<string, MaKey> = { MA5: "ma5", MA10: "ma10", MA20: "ma20", MA60: "ma60" };

type LegendSelectEvent = { name: string; selected: Record<string, boolean> };

function isLegendSelectEvent(value: unknown): value is LegendSelectEvent {
  return typeof value === "object" && value !== null && "name" in value && "selected" in value;
}

export default function Home() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<IndicatorTab>("macd");
  const [period, setPeriod] = useState<PeriodKey>("day");
  const [ma, setMa] = useState<MaVisible>(ALL_MA);
  const [chatOpen, setChatOpen] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInst = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API}/api/watchlist`).then((r) => r.json()),
      fetch(`${API}/api/stocks`).then((r) => r.json()),
    ])
      .then(([watch, all]: [WatchItem[], Stock[]]) => {
        setWatchlist(watch);
        setStocks(all);
        if (watch.length > 0) {
          setCode(watch[0].code);
          setName(watch[0].name);
        }
      })
      .catch(() => setError("无法连接后端 API"));
  }, []);

  const load = useCallback((c: string, p: PeriodKey) => {
    if (!c) return;
    setRows(null);
    setError("");
    fetch(`${API}/api/indicators/${c}?period=${p}`)
      .then((res) => {
        if (res.status === 404) throw new Error("EMPTY");
        if (!res.ok) throw new Error("BACKEND");
        return res.json();
      })
      .then((data: { rows: Row[] }) => setRows(data.rows))
      .catch((e: Error) =>
        setError(
          e.message === "EMPTY"
            ? `${c} 暂无行情数据：这只股票还没同步过，请到「选股」页把它加入自选或应用池子，系统会自动同步`
            : e.message === "BACKEND"
              ? "无法连接后端 API（:8000），请确认服务已启动"
              : e.message,
        ),
      );
  }, []);

  useEffect(() => {
    load(code, period);
  }, [code, period, load]);

  useEffect(() => {
    if (!chartRef.current || !rows || rows.length === 0) return;
    const inst = chartInst.current ?? echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    chartInst.current = inst;
    inst.setOption(buildChartOption(rows, tab, ma), true);
    const obs = new ResizeObserver(() => inst.resize());
    obs.observe(chartRef.current);
    const onLegend = (...args: unknown[]) => {
      const payload = args[0];
      if (!isLegendSelectEvent(payload)) return;
      const key = MA_BY_LABEL[payload.name];
      if (!key) return;
      setMa((prev) => ({ ...prev, [key]: payload.selected[payload.name] }));
    };
    inst.on("legendselectchanged", onLegend);
    return () => {
      obs.disconnect();
      inst.off("legendselectchanged", onLegend);
    };
  }, [rows, tab, ma]);

  useEffect(() => () => chartInst.current?.dispose(), []);

  const pick = (s: Stock | WatchItem) => {
    setCode(s.code);
    setName(s.name);
    setQuery("");
    setOpen(false);
  };

  const shown = query
    ? stocks.filter((s) => s.code.includes(query) || s.name.includes(query)).slice(0, 50)
    : watchlist.slice(0, 50);
  const watchCodes = new Set(watchlist.map((w) => w.code));

  const last = rows && rows.length > 0 ? rows[rows.length - 1] : null;
  const prev = rows && rows.length > 1 ? rows[rows.length - 2] : null;
  const chg = last && prev ? ((last.close - prev.close) / prev.close) * 100 : null;

  return (
    <main>
      <div className="topbar">
        <span className="brand">个股分析</span>
        <nav className="screen-nav">
          <a href="/" className="active">
            分析
          </a>
          <a href="/screen">选股</a>
          <a href="/learn">学习</a>
        </nav>
        <div className="search-wrap">
          <input
            placeholder="搜索代码 / 名称…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
          />
          {open && (
            <div className="dropdown">
              {shown.length === 0 && <button disabled>无匹配结果</button>}
              {shown.map((s) => (
                <button key={s.code} onMouseDown={() => pick(s)}>
                  <span>
                    {watchCodes.has(s.code) ? <span className="star">★ </span> : null}
                    {s.name}
                  </span>
                  <span className="code">{s.code}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {code && (
          <div className="stock-head">
            <span className="name">{name}</span>
            <span className="code">{code}</span>
            {last && (
              <>
                <span className={`price ${chg !== null && chg >= 0 ? "up" : "down"}`} style={{ color: chg !== null && chg >= 0 ? "var(--up)" : "var(--down)" }}>
                  {last.close.toFixed(2)}
                </span>
                <span className={`chg ${chg !== null && chg >= 0 ? "up" : "down"}`}>
                  {chg !== null ? `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : ""}
                </span>
              </>
            )}
          </div>
        )}
      </div>

      <div className="body">
        <div className="main-col">
          <div className="chart-head">
            <div className="tabs">
              {PERIODS.map((p) => (
                <button key={p.key} className={period === p.key ? "active" : ""} onClick={() => setPeriod(p.key)}>
                  {p.label}
                </button>
              ))}
            </div>
            {code && (
            <div>
              <button className="ai-toggle" onClick={() => setChatOpen((v) => !v)}>
                {chatOpen ? "收起解读" : "AI解读"}
              </button>
              <button className="ai-toggle" onClick={() => {
                postJson(`/api/report/${code}/generate`, { code });
                alert("报告生成中，请查看学习页");
              }}>
                生成报告
              </button>
            </div>
          )}
          </div>
          {error && <div className="center-msg">{error}</div>}
          {!error && !rows && <div className="center-msg">加载中…</div>}
          {!error && rows && rows.length === 0 && <div className="center-msg">该股票无数据</div>}
          <div ref={chartRef} className="chart" style={{ display: rows && rows.length > 0 ? "block" : "none" }} />
          <div className="ind-bar">
            {TABS.map((t) => (
              <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
                {t.label}
              </button>
            ))}
            <span className="hint">周期涨跌幅基于所选 K 线</span>
          </div>
        </div>
        {code && chatOpen && <ChatPanel code={code} onClose={() => setChatOpen(false)} />}
      </div>
    </main>
  );
}
