"use client";

type Factor = {
  signal: string;
  delta_pct: number;
  strength: string;
};

type Explanation = {
  headline?: string;
  likely_cause?: string;
  confidence?: number;
  narrative?: string;
  factors?: Factor[];
  start_date?: string;
  end_date?: string;
  level?: string;
};

function strengthColor(strength: string): string {
  if (strength === "strong") return "var(--accent-critical)";
  if (strength === "moderate") return "var(--accent-warning)";
  return "var(--text-muted)";
}

function strengthLabel(strength: string): string {
  if (strength === "strong") return "сильный сигнал";
  if (strength === "moderate") return "умеренный сигнал";
  return "слабый сигнал";
}

function FactorBar({ factor }: { factor: Factor }) {
  const abs = Math.min(100, Math.abs(factor.delta_pct));
  const sign = factor.delta_pct > 0 ? "+" : "";
  const isNeg = factor.delta_pct < 0;

  return (
    <div className="factor-row">
      <div className="factor-header">
        <span className="factor-signal">{factor.signal}</span>
        <span className="factor-delta" style={{ color: isNeg ? "var(--accent-critical)" : "var(--accent-info)" }}>
          {sign}{factor.delta_pct}%
        </span>
        <span className="factor-strength" style={{ color: strengthColor(factor.strength) }}>
          {strengthLabel(factor.strength)}
        </span>
      </div>
      <div className="factor-bar-track">
        <div
          className="factor-bar-fill"
          style={{
            width: `${abs}%`,
            background: isNeg ? "var(--accent-critical)" : "var(--accent-info)",
          }}
        />
      </div>
    </div>
  );
}

const LEVEL_LABELS: Record<string, { label: string; color: string }> = {
  critical: { label: "Критическая аномалия", color: "var(--accent-critical)" },
  stress: { label: "Стресс вегетации", color: "var(--accent-warning)" },
  watch: { label: "Снижение биомассы", color: "var(--accent-info)" },
  normal: { label: "Норма", color: "var(--accent-vegetation)" },
};

export default function AnomalyCard({ explanation }: { explanation: Explanation }) {
  if (!explanation) return null;

  const level = LEVEL_LABELS[explanation.level || "normal"] || LEVEL_LABELS.normal;

  return (
    <div className="anomaly-card">
      <div className="anomaly-header">
        <span className="anomaly-title">Почему это аномалия?</span>
        <span className="anomaly-badge" style={{ background: level.color, color: "#000" }}>
          {level.label}
        </span>
      </div>

      {explanation.headline && (
        <p className="anomaly-headline">{explanation.headline}</p>
      )}

      <div className="anomaly-period">
        <span className="anomaly-period-icon">◉</span>
        {explanation.start_date} — {explanation.end_date}
      </div>

      {explanation.factors?.length ? (
        <div className="anomaly-factors">
          {explanation.factors.map((f) => (
            <FactorBar key={f.signal} factor={f} />
          ))}
        </div>
      ) : null}

      <div className="anomaly-conclusion">
        <div className="anomaly-cause">
          <span className="anomaly-cause-label">Вывод</span>
          <span className="anomaly-cause-value">{explanation.likely_cause}</span>
        </div>
        <div className="anomaly-confidence">
          <span className="anomaly-cause-label">Уверенность</span>
          <span className="anomaly-confidence-value">
            {Math.round((explanation.confidence || 0) * 100)}%
          </span>
        </div>
      </div>

      {explanation.narrative && (
        <p className="anomaly-narrative">{explanation.narrative}</p>
      )}
    </div>
  );
}
