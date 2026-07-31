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
    core: row?.pool_rank === 1,
    coreLabel: row?.pool_rank === 1 ? "核心 Top1" : "",
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

export function bHeatmapMarker(row, minimumDuration = 3) {
  const visual = bVisualState(row);
  const duration = Number(row?.weak_duration || 0);
  const top1 = row?.pool_rank === 1;
  const attention =
    visual.status !== "stable" && duration >= minimumDuration;
  const label = top1
    ? attention
      ? `B Top1 · 走弱已持续${duration}日`
      : `B Top1 · ${row?.b_count || 0}只`
    : attention
      ? `${row?.formal_cooling ? "B已确认降温" : "B走弱"} · 已持续${duration}日`
      : "";
  return {
    visible: top1 || attention,
    top1,
    attention,
    tone: row?.formal_cooling ? "danger" : attention ? "warning" : "stable",
    label,
  };
}
