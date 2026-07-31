export const B_STATUS = {
  stable: {
    label: "B稳定",
    tone: "stable",
  },
  weakening: {
    label: "B走弱",
    tone: "warning",
  },
  cooling: {
    label: "已确认降温",
    tone: "danger",
  },
};

export function bVisualState(row) {
  const status = row?.formal_cooling
    ? "cooling"
    : row?.smooth3_weak || row?.smooth5_weak
      ? "weakening"
      : "stable";
  return {
    ...B_STATUS[status],
    status,
    core: row?.pool_rank === 1 || row?.pool_rank === 2,
    coreLabel:
      row?.pool_rank === 1
        ? "核心 Top1"
        : row?.pool_rank === 2
          ? "核心 Top2"
          : "",
  };
}

export function bChangeText(value) {
  if (!Number.isFinite(value)) return "—";
  const rounded = Math.round(value * 10) / 10;
  if (rounded > 0) return `+${rounded}只`;
  return `${rounded}只`;
}

export function bDurationText(row) {
  return row?.weak_duration > 0
    ? `B走弱状态已持续${row.weak_duration}个交易日`
    : "";
}
