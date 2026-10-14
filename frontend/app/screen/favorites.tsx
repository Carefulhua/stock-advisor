"use client";

import { useEffect, useState } from "react";
import { deleteJson, getJson, postJson } from "../api";
import type { AddResult, Favorite } from "./types";

type Stock = { code: string; name: string };

type Props = {
  favorites: Favorite[];
  onChange: () => void;
  onError: (msg: string) => void;
  onSynced: () => void;
};

function splitCodes(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,，;；\t]+/)
        .map((s) => s.trim())
        .filter((s) => /^\d{1,6}$/.test(s)),
    ),
  );
}

export default function FavoritesPanel({ favorites, onChange, onError, onSynced }: Props) {
  const [query, setQuery] = useState("");
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [picked, setPicked] = useState("");
  const [bulk, setBulk] = useState("");
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (query.trim() === "") {
      setStocks([]);
      return;
    }
    const timer = setTimeout(() => {
      setSearching(true);
      getJson<Stock[]>(`/api/stocks/search?q=${encodeURIComponent(query.trim())}`)
        .then(setStocks)
        .catch(() => {
          setStocks([]);
          onError("全市场搜索失败：行情快照未能加载，请稍后重试");
        })
        .finally(() => setSearching(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [query, onError]);

  const add = async (codes: string[]) => {
    if (codes.length === 0) return;
    setBusy(true);
    try {
      const res = await postJson<AddResult>("/api/favorites", { codes });
      const parts = [`新增 ${res.added} 只`];
      if (res.skipped > 0) parts.push(`跳过 ${res.skipped} 只（无效或已存在）`);
      if (res.sync_job_id) parts.push("已开始后台同步这批股票的日线与财务，稍候即可在分析页查看");
      else if (res.added > 0) parts.push("未触发同步（已有同步任务在运行），可稍后重新添加或到选股页应用池子");
      setQuery("");
      setPicked("");
      setBulk("");
      onError("");
      window.alert(parts.join("，"));
      if (res.sync_job_id) onSynced();
      onChange();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (code: string) => {
    setBusy(true);
    try {
      await deleteJson<{ deleted: boolean }>(`/api/favorites/${code}`);
      onChange();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fav-panel">
      <div className="fav-row">
        <div className="fav-search">
          <input
            placeholder="搜索全市场代码/名称（5000+ 只），如 600036 或 招商银行"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {stocks.length > 0 && (
            <div className="fav-dropdown">
              {stocks.map((s) => (
                <button
                  key={s.code}
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setPicked(s.code);
                    void add([s.code]);
                  }}
                >
                  <span>{s.name}</span>
                  <span className="code">{s.code}</span>
                </button>
              ))}
            </div>
          )}
          {searching && stocks.length === 0 && (
            <div className="fav-dropdown">
              <button type="button" disabled>
                正在加载全市场列表，首次约 10 秒…
              </button>
            </div>
          )}
        </div>
        <button type="button" disabled={busy || picked.length === 0} onClick={() => void add([picked])}>
          加入自选
        </button>
      </div>

      <div className="fav-bulk">
        <textarea
          placeholder="批量添加：粘贴代码，逗号或空格分隔，例如 600519, 000001 300750"
          value={bulk}
          onChange={(e) => setBulk(e.target.value)}
        />
        <button type="button" disabled={busy || splitCodes(bulk).length === 0} onClick={() => void add(splitCodes(bulk))}>
          批量添加
        </button>
      </div>

      <div className="fav-list">
        {favorites.length === 0 && <div className="cond-hint">暂无自选股。自选股会强制保留在池子里，不参与排名。</div>}
        {favorites.map((f) => (
          <div className="fav-item" key={f.code}>
            <span>{f.name}</span>
            <span className="code">{f.code}</span>
            <button type="button" disabled={busy} onClick={() => void remove(f.code)}>
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}