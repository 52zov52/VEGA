"use client";

type KPIData = {
  current_ndvi?: number;
  season_deviation_pct?: number;
  level?: string;
  data_quality?: number;
  anomaly_score?: number;
};

const LEVEL_META: Record<string, { label: string; color: string; icon: string }> = {
  normal: { label: "Норма", color: "var(--accent-vegetation)", icon: "●" },
  watch: { label: "Наблюдение", color: "var(--accent-info)", icon: "◐" },
  stress: { label: "Стресс", color: "var(--accent-warning)", icon: "◑" },
  critical: { label: "Критично", color: "var(--accent-critical)", icon: "◉" },
};

export default function KPI({ data }: { data: KPIData }) {
  if (!data?.current_ndvi) return null;
  const meta = LEVEL_META[data.level || "normal"] || LEVEL_META.normal;

  return (
    <div className="kpi-grid">
      <div className="kpi-card">
        <span className="kpi-label">Текущий NDVI</span>
        <span className="kpi-value">{data.current_ndvi}</span>
      </div>
      <div className="kpi-card">
        <span className="kpi-label">Отклонение</span>
        <span className="kpi-value" style={{
          color: (data.season_deviation_pct || 0) < -10
            ? "var(--accent-critical)" : (data.season_deviation_pct || 0) < -5
            ? "var(--accent-warning)" : "var(--accent-vegetation)",
        }}>
          {data.season_deviation_pct != null && data.season_deviation_pct > 0 ? "+" : ""}{data.season_deviation_pct ?? "—"}%
        </span>
      </div>
      <div className="kpi-card">
        <span className="kpi-label">Риск</span>
        <span className="kpi-value" style={{ color: meta.color }}>
          {meta.icon} {meta.label}
        </span>
      </div>
      <div className="kpi-card">
        <span className="kpi-label">Качество</span>
        <span className="kpi-value">{data.data_quality ?? "—"}%</span>
      </div>
    </div>
  );
}
