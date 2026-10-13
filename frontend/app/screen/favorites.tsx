"use client";

import { useEffect, useState } from "react";
import { deleteJson, getJson, postJson } from "../api";
import type { AddResult, Favorite } from "./types";

type Stock = { code: string; name: string };

type Props = {
  favorites: Favorite[];
  onChange: () => void;
  onError: (msg: string) => void;
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

export default function FavoritesPanel({ favorites, onChange, onError }: Props) {
  const [query, setQuery] = useState("");
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [picked, setPicked] = useState("");
  const [bulk, setBulk] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (query.trim() === "") {
      setStocks([]);
      return;
    }
    const timer = setTimeout(() => {
      getJson<Stock[]>("/api/stocks")
        .then((all) => {
          const q = query.trim();
          setStocks(all.filter((s) => s.code.includes(q) || s.name.includes(q)).slice(0, 20));
        })
        .catch(() => setStocks([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [query]);

  const add = async (codes: string[]) => {
    if (codes.length === 0) return;
    setBusy(true);
    try {
      const res = await postJson<AddResult>("/api/favorites", { codes });
      const msg = `新增 ${res.added} 只` + (res.skipped > 0 ? `，跳过 ${res.skipped} 只（无效或已存在）` : "");
      setQuery("");
      setPicked("");
      setBulk("");
      onError("");
      window.alert(msg);
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
            placeholder="搜索代码/名称后加入自选"
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