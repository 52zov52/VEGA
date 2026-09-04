"use client";

export function LoadingSkeleton({ text = "Загрузка…" }: { text?: string }) {
  return (
    <div className="ui-state ui-loading" role="status" aria-label={text}>
      <div className="ui-state-spinner" />
      <span className="ui-state-text">{text}</span>
    </div>
  );
}

export function EmptyState({ text, icon = "◇" }: { text: string; icon?: string }) {
  return (
    <div className="ui-state ui-empty" role="status">
      <span className="ui-state-icon">{icon}</span>
      <span className="ui-state-text">{text}</span>
    </div>
  );
}

export function ErrorState({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="ui-state ui-error" role="alert">
      <span className="ui-state-icon">⚠</span>
      <span className="ui-state-text">{text}</span>
      {onRetry && (
        <button className="btn-secondary btn-sm" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function PipelineState() {
  return (
    <div className="pipeline-state">
      <div className="pipeline-steps">
        {["Спутник", "Очистка", "Ряд", "ML", "Аномалия", "Объяснение"].map((step, i) => (
          <div key={step} className="pipeline-step">
            <div className="pipeline-dot active" />
            <span>{step}</span>
          </div>
        ))}
      </div>
      <span className="pipeline-label">Сбор данных и анализ…</span>
    </div>
  );
}
