export type Row = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma60: number | null;
  dif: number | null;
  dea: number | null;
  macd_hist: number | null;
  rsi14: number | null;
  k: number | null;
  d: number | null;
  j: number | null;
};

export type IndicatorTab = "macd" | "rsi" | "kdj";

const UP = "#f5333f";
const DOWN = "#14b866";
const MA_COLORS: Record<string, string> = {
  ma5: "#4a8cff",
  ma10: "#e6b800",
  ma20: "#c678dd",
  ma60: "#56b6c2",
};

const textColor = "#8a93a6";
const axisLine = { lineStyle: { color: "#262d3d" } };
const splitLine = { lineStyle: { color: "#1c2230" } };
const axisLabel = { color: textColor, fontSize: 11 };

function maSeries(key: "ma5" | "ma10" | "ma20" | "ma60", rows: Row[]) {
  return {
    name: key.toUpperCase(),
    type: "line" as const,
    xAxisIndex: 0,
    yAxisIndex: 0,
    data: rows.map((r) => r[key]),
    showSymbol: false,
    lineStyle: { width: 1.2, color: MA_COLORS[key] },
    itemStyle: { color: MA_COLORS[key] },
  };
}

function volumeSeries(rows: Row[]) {
  return [
    {
      name: "成交量",
      type: "bar" as const,
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: rows.map((r) => ({
        value: r.volume,
        itemStyle: { color: r.close >= r.open ? UP : DOWN },
      })),
    },
  ];
}

function indicatorSeries(rows: Row[], tab: IndicatorTab) {
  if (tab === "macd") {
    return [
      {
        name: "MACD",
        type: "bar" as const,
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: rows.map((r) => ({
          value: r.macd_hist,
          itemStyle: { color: (r.macd_hist ?? 0) >= 0 ? UP : DOWN },
        })),
      },
      {
        name: "DIF",
        type: "line" as const,
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: rows.map((r) => r.dif),
        showSymbol: false,
        lineStyle: { width: 1.2, color: MA_COLORS.ma5 },
      },
      {
        name: "DEA",
        type: "line" as const,
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: rows.map((r) => r.dea),
        showSymbol: false,
        lineStyle: { width: 1.2, color: MA_COLORS.ma10 },
      },
    ];
  }
  if (tab === "rsi") {
    return [
      {
        name: "RSI14",
        type: "line" as const,
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: rows.map((r) => r.rsi14),
        showSymbol: false,
        lineStyle: { width: 1.2, color: MA_COLORS.ma5 },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: "#3a4358", type: "dashed" },
          label: { color: textColor, fontSize: 10 },
          data: [
            { yAxis: 70, label: { formatter: "70" } },
            { yAxis: 30, label: { formatter: "30" } },
          ],
        },
      },
    ];
  }
  const line = (name: "k" | "d" | "j", color: string) => ({
    name: name.toUpperCase(),
    type: "line" as const,
    xAxisIndex: 2,
    yAxisIndex: 2,
    data: rows.map((r) => r[name]),
    showSymbol: false,
    lineStyle: { width: 1.2, color },
  });
  return [
    line("k", MA_COLORS.ma5),
    line("d", MA_COLORS.ma10),
    {
      ...line("j", MA_COLORS.ma20),
      markLine: {
        silent: true,
        symbol: "none",
        lineStyle: { color: "#3a4358", type: "dashed" },
        label: { color: textColor, fontSize: 10 },
        data: [
          { yAxis: 80, label: { formatter: "80" } },
          { yAxis: 20, label: { formatter: "20" } },
        ],
      },
    },
  ];
}

function fmtShort(v: number): string {
  if (Math.abs(v) >= 1e8) return `${+(v / 1e8).toFixed(2)}亿`;
  if (Math.abs(v) >= 1e4) return `${+(v / 1e4).toFixed(1)}万`;
  return `${v}`;
}

function fmtTooltip(v: unknown): unknown {
  if (Array.isArray(v)) return v;
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-US") : +v.toFixed(4);
  }
  return v;
}

export function buildChartOption(rows: Row[], tab: IndicatorTab) {
  const dates = rows.map((r) => r.date.slice(0, 10));
  const candle = rows.map((r) => [r.open, r.close, r.low, r.high]);
  const visible = Math.min(rows.length, 180);
  const start = rows.length ? (100 * (rows.length - visible)) / rows.length : 0;

  const mainSeries = [
    {
      name: "K线",
      type: "candlestick" as const,
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: candle,
      itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
    },
    maSeries("ma5", rows),
    maSeries("ma10", rows),
    maSeries("ma20", rows),
    maSeries("ma60", rows),
  ];
  const indSeries = indicatorSeries(rows, tab);
  const legendData = [
    ...mainSeries.slice(1).map((s) => s.name),
    ...indSeries.map((s) => s.name),
  ];

  return {
    animation: false,
    backgroundColor: "transparent",
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    legend: {
      data: legendData,
      top: 4,
      left: 10,
      textStyle: { color: textColor, fontSize: 11 },
      icon: "rect",
      itemWidth: 10,
      itemHeight: 3,
    },
    tooltip: { trigger: "axis" as const, axisPointer: { type: "cross" as const }, valueFormatter: fmtTooltip },
    grid: [
      { left: 60, right: 76, top: 30, height: "48%" },
      { left: 60, right: 76, top: "56%", height: "13%" },
      { left: 60, right: 76, top: "74%", height: "16%" },
    ],
    xAxis: [0, 1, 2].map((i) => ({
      type: "category" as const,
      gridIndex: i,
      data: dates,
      axisLine,
      axisLabel: i === 2 ? { ...axisLabel, formatter: (v: string) => v } : { ...axisLabel, show: false },
      boundaryGap: true,
      splitLine: { show: false },
    })),
    yAxis: [
      { gridIndex: 0, position: "right" as const, scale: true as const, axisLine, splitLine, axisLabel },
      {
        gridIndex: 1,
        position: "right" as const,
        scale: true as const,
        axisLine,
        splitLine,
        splitNumber: 2,
        axisLabel: { ...axisLabel, formatter: fmtShort },
      },
      { gridIndex: 2, position: "right" as const, scale: true as const, axisLine, splitLine, axisLabel, splitNumber: 3 },
    ],
    dataZoom: [
      { type: "inside" as const, xAxisIndex: [0, 1, 2], start, end: 100 },
      {
        type: "slider" as const,
        xAxisIndex: [0, 1, 2],
        bottom: 6,
        height: 14,
        borderColor: "#262d3d",
        backgroundColor: "#161b26",
        fillerColor: "rgba(74,140,255,0.15)",
        handleStyle: { color: "#4a8cff" },
        textStyle: { color: textColor, fontSize: 10 },
        start,
        end: 100,
      },
    ],
    series: [...mainSeries, ...volumeSeries(rows), ...indSeries],
  };
}
