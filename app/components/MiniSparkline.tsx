export function MiniSparkline({ values = [], tone = "mint" }: { values?: number[]; tone?: "mint" | "blue" | "lime" }) {
  if (!values.length) return <span className="spark-empty">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const points = values.map((v, i) => {
    const x = (i / Math.max(values.length - 1, 1)) * 70;
    const y = 27 - ((v - min) / Math.max(max - min, 0.0001)) * 23;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg className={`sparkline ${tone}`} viewBox="0 0 70 31" aria-hidden="true">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
