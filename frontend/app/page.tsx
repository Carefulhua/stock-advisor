"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import ChatPanel from "./ChatPanel";
import { buildChartOption, IndicatorTab, Row } from "./chartOption";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type Stock = { code: string; name: string; in_watchlist: boolean };
type WatchItem = { code: string; name: string; rank: number };

const RANGES = [
  { key: "3m", label: "近3月", days: 92 },
  { key: "1y", label: "近1年", days: 366 },
  { key: "3y", label: "近3年", days: 1096 },
  { key: "all", label: "全部", days: 0 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

const TABS: { key: IndicatorTab; label: string }[] = [
  { key: "macd", label: "MACD" },
  { key: "rsi", label: "RSI(14)" },
  { key: "kdj", label: "KDJ(9,3,3)" },
];

function startFor(range: RangeKey): string | undefined {
  const days = RANGES.find((r) => r.key === range)!.days;
  if (!days) return undefined;
  const d = new Date();
  d.setDate(d.getDate() - days);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
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
  const [range, setRange] = useState<RangeKey>("1y");
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

  const load = useCallback((c: string, r: RangeKey) => {
    if (!c) return;
    setRows(null);
    setError("");
    const start = startFor(r);
    const url = `${API}/api/indicators/${c}${start ? `?start=${start}` : ""}`;
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error("404");
        return res.json();
      })
      .then((data: { rows: Row[] }) => setRows(data.rows))
      .catch(() => setError(`加载 ${c} 失败：无数据或后端未启动`));
  }, []);

  useEffect(() => {
    load(code, range);
  }, [code, range, load]);

  useEffect(() => {
    if (!chartRef.current || !rows || rows.length === 0) return;
    const inst = chartInst.current ?? echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    chartInst.current = inst;
    inst.setOption(buildChartOption(rows, tab), true);
    const obs = new ResizeObserver(() => inst.resize());
    obs.observe(chartRef.current);
    return () => obs.disconnect();
  }, [rows, tab]);

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

      <div className="toolbar">
        <div className="group">
          {RANGES.map((r) => (
            <button key={r.key} className={range === r.key ? "active" : ""} onClick={() => setRange(r.key)}>
              {r.label}
            </button>
          ))}
        </div>
        <span className="sep" />
        <div className="group">
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
        {code && (
          <button className="ai-toggle" onClick={() => setChatOpen((v) => !v)}>
            {chatOpen ? "收起解读" : "AI解读"}
          </button>
        )}
      </div>

      <div className="body">
        <div className="main-col">
          {error && <div className="center-msg">{error}</div>}
          {!error && !rows && <div className="center-msg">加载中…</div>}
          {!error && rows && rows.length === 0 && <div className="center-msg">该股票无数据</div>}
          <div ref={chartRef} className="chart" style={{ display: rows && rows.length > 0 ? "block" : "none" }} />
        </div>
        {code && chatOpen && <ChatPanel code={code} onClose={() => setChatOpen(false)} />}
      </div>
    </main>
  );
}
