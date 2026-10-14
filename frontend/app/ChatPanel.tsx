"use client";

import { useEffect, useRef, useState } from "react";

import { API } from "./api";

type ChatMsg = { role: "user" | "assistant"; content: string };

interface ChatPanelProps {
  code: string;
  onClose: () => void;
}

export default function ChatPanel({ code, onClose }: ChatPanelProps) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    setMsgs([]);
    setError("");
    fetch(`${API}/api/chat/${code}/history`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`加载历史失败(${res.status})`))))
      .then((data: ChatMsg[]) => {
        if (alive) setMsgs(data.map((m) => ({ role: m.role, content: m.content })));
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [code]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs]);

  async function send() {
    const question = input.trim();
    if (!question || busy) return;
    const next: ChatMsg[] = [...msgs, { role: "user", content: question }];
    setMsgs(next);
    setInput("");
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, messages: next }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.text().catch(() => "");
        throw new Error(`请求失败(${res.status}) ${detail}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        const current = acc;
        setMsgs([...next, { role: "assistant", content: current }]);
      }
      if (!acc) throw new Error("模型未返回内容");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || "连接中断，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="chat-panel">
      <div className="chat-head">
        <span>AI 解读 · {code}</span>
        <button onClick={onClose} aria-label="关闭">✕</button>
      </div>
      <div className="chat-body" ref={scrollRef}>
        {msgs.length === 0 && (
          <div className="chat-empty">
            针对当前股票提问，数据由后端计算层注入，AI只做解读。
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <pre>{m.content}</pre>
            {busy && m.role === "assistant" && i === msgs.length - 1 && (
              <span className="chat-cursor" />
            )}
          </div>
        ))}
        {error && <div className="chat-error">{error}</div>}
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          placeholder="Enter 发送，Shift+Enter 换行"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          disabled={busy}
          rows={2}
        />
        <button onClick={() => void send()} disabled={busy || !input.trim()}>
          {busy ? "…" : "发送"}
        </button>
      </div>
    </aside>
  );
}
