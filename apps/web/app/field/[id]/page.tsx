"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import * as echarts from "echarts";
import KPI from "../../../components/KPI";
import AnomalyCard from "../../../components/AnomalyCard";
import { getCropRu } from "../../../components/Globe";
import { LoadingSkeleton, EmptyState, ErrorState, PipelineState } from "../../../components/UIStates";
import { fetchAnalysis, fetchForecast, type FieldAnalysis, type ForecastPoint } from "../../../lib/api";

const LEVEL_RU: Record<string, string> = {
  normal: "Норма",
  watch: "Наблюдение",
  stress: "Стресс",
  critical: "Критично",
};

const RECOMMEND: Record<string, string> = {
  normal: "Продолжить регламентный мониторинг. Внеплановых выездов не требуется.",
  watch: "Усилить наблюдение: повторный анализ через 7–10 дней, проверить осадки и влагозапас.",
  stress: "Рекомендуется полевое обследование проблемных зон и проверка питания/влаги.",
  critical: "Срочное полевое обследование. Вероятны потери урожая — оценить пересев или обработку.",
};

const KIND_RU: Record<string, string> = {
  sustained: "устойчивый",
  spike: "всплеск",
  early_warning: "ранний сигнал",
  uncertain: "низкое качество данных",
};

function spanDays(a: any): string {
  try {
    const d = (new Date(a.end_date).getTime() - new Date(a.start_date).getTime()) / 86400000 + 1;
    if (!isFinite(d) || d <= 0) return "";
    return `≈${Math.round(d)} дн.`;
  } catch { return ""; }
}

function fmtDate(d?: string) {
  if (!d) return "—";
  return d.slice(0, 10);
}

export default function FieldPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const id = decodeURIComponent(params.id || "");
  const regionId = search.get("region") || "rostov";

  const chartRef = useRef<HTMLDivElement>(null);
  const fcRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<FieldAnalysis | null>(null);
  const [forecast, setForecast] = useState<ForecastPoint[]>([]);
  const [meta, setMeta] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [entered, setEntered] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [showLayers, setShowLayers] = useState({ ndvi: true, anomaly: true });

  // Плавное проявление из чёрного при загрузке страницы —
  // вторая половина «незаметного» перехода с глобуса.
  useEffect(() => {
    const t = requestAnimationFrame(() => requestAnimationFrame(() => setEntered(true)));
    return () => cancelAnimationFrame(t);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        // Метаданные поля: ищем среди контуров региона и своих полигонов
        let center: any = null;
        try {
          const [fj, pj] = await Promise.all([
            fetch(`${API}/api/regions/${regionId}/fields?limit=200`).then((x) => x.json()).catch(() => ({})),
            fetch(`${API}/api/polygons`).then((x) => x.json()).catch(() => ({})),
          ]);
          const found =
            (fj.fields || []).find((f: any) => f.id === id) ||
            (pj.polygons || []).find((p: any) => p.id === id);
          if (!cancelled && found) setMeta(found);
          center = found?.center || null;
        } catch { /* метаданные необязательны */ }
        // Погода и анализ — по координатам ЭТОГО поля, а не дефолтного региона
        const opts = center && center.length === 2 && isFinite(Number(center[0])) && isFinite(Number(center[1]))
          ? { lat: Number(center[0]), lon: Number(center[1]) } : {};
        const full = await fetchAnalysis(id, regionId, opts);
        if (!cancelled) setData(full);
        // прогноз — отдельным запросом, не блокирует основной анализ
        if (!cancelled && (full as any).analysis_id) {
          fetchForecast((full as any).analysis_id, 14)
            .then((fc) => { if (!cancelled) setForecast(fc); })
            .catch(() => { /* прогноз экспериментальный — молча пропускаем */ });
        }
      } catch (e: any) {
        if (!cancelled) setError(`Анализ недоступен: ${e.message}.`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => { cancelled = true; };
  }, [id, regionId]);

  const ts = data?.ts || [];
  const kpi = data?.kpi || {};
  const level = kpi.level || "normal";

  const stats = useMemo(() => {
    if (!ts.length) return null;
    const ndvi = ts.map((p) => p.ndvi_observed).filter((v) => typeof v === "number");
    const prec = ts.map((p) => p.precipitation).filter((v) => typeof v === "number");
    const anomDays = ts.filter((p) => p.anomaly).length;
    const mean = ndvi.length ? ndvi.reduce((a, b) => a + b, 0) / ndvi.length : null;
    // Недобор биомассы за сезон (эвристика): суммарный дефицит NDVI
    // относительно нормы, делённый на суммарную норму. 0% = шли по норме.
    let num = 0, den = 0;
    for (const p of ts) {
      if (typeof p.ndvi_observed === "number" && typeof p.ndvi_climatology === "number" && p.ndvi_climatology > 0.05) {
        num += Math.max(0, p.ndvi_climatology - p.ndvi_observed);
        den += p.ndvi_climatology;
      }
    }
    const deficit = den > 0 ? (num / den) * 100 : null;
    return {
      points: ts.length,
      period: `${fmtDate(ts[0]?.date)} — ${fmtDate(ts[ts.length - 1]?.date)}`,
      mean: mean != null ? mean.toFixed(3) : "—",
      min: ndvi.length ? Math.min(...ndvi).toFixed(3) : "—",
      max: ndvi.length ? Math.max(...ndvi).toFixed(3) : "—",
      precip: prec.length ? Math.round(prec.reduce((a, b) => a + b, 0)) : "—",
      anomDays,
      deficit: deficit != null ? deficit.toFixed(1) : "—",
    };
  }, [ts]);

  const fcSummary = useMemo(() => {
    if (!forecast.length || !ts.length) return null;
    const lastObs = ts[ts.length - 1].ndvi_observed;
    const base = typeof lastObs === "number" ? lastObs : forecast[0].ndvi;
    const last = forecast[forecast.length - 1];
    const d = last.ndvi - base;
    const days = Math.round((new Date(last.date).getTime() - new Date(String(ts[ts.length - 1].date)).getTime()) / 86400000);
    const dir = d > 0.02 ? "рост" : d < -0.02 ? "снижение" : "плато";
    const unc = last.hi - last.lo;
    return { dir, d, days, unc };
  }, [forecast, ts]);

  function downloadCSV() {    const head = "date,ndvi_observed,ndvi_climatology,precipitation,anomaly,ndvi_forecast,forecast_lo,forecast_hi";
    const fcMap = new Map(forecast.map((f) => [f.date.slice(0, 10), f]));
    const lines = ts.map((p) => {
      const d = String(p.date).slice(0, 10);
      const f = fcMap.get(d);
      return [d, p.ndvi_observed ?? "", p.ndvi_climatology ?? "", p.precipitation ?? "",
        p.anomaly ? 1 : 0, f?.ndvi ?? "", f?.lo ?? "", f?.hi ?? ""].join(",");
    });
    for (const f of forecast) {
      const d = f.date.slice(0, 10);
      if (!ts.some((p) => String(p.date).slice(0, 10) === d)) {
        lines.push([d, "", "", "", "", f.ndvi, f.lo, f.hi].join(","));
      }
    }
    const blob = new Blob([[head, ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${id}_analysis.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Мини-график прогноза
  useEffect(() => {
    if (!fcRef.current || !forecast.length) return;
    const chart = echarts.init(fcRef.current);
    const lastObs = ts.length ? ts.slice(-12) : [];
    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: 600,
      tooltip: {
        trigger: "axis",
        backgroundColor: "#181d17ee",
        borderColor: "#2a3029",
        textStyle: { color: "#f2f4ec", fontSize: 12 },
      },
      legend: { data: ["Факт", "Прогноз"], textStyle: { color: "#a8b09f", fontSize: 11 }, top: 0 },
      grid: { left: 50, right: 16, bottom: 30, top: 40 },
      xAxis: {
        type: "category",
        data: [...lastObs.map((p) => String(p.date).slice(0, 10)), ...forecast.map((f) => f.date.slice(0, 10))],
        axisLabel: { color: "#a8b09f", fontSize: 10 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#a8b09f", fontSize: 10 },
        splitLine: { lineStyle: { color: "#1e241c" } },
      },
      series: [
        {
          name: "Факт", type: "line",
          data: [...lastObs.map((p) => p.ndvi_observed), ...forecast.map(() => null)],
          lineStyle: { width: 2, color: "#7cc46a" }, symbol: "none",
        },
        {
          name: "Прогноз", type: "line",
          data: [...lastObs.map(() => null), ...forecast.map((f) => f.ndvi)],
          lineStyle: { type: "dashed", width: 2, color: "#29b6f6" }, symbol: "circle", symbolSize: 5,
        },
        {
          name: "Коридор", type: "line",
          data: [...lastObs.map(() => null), ...forecast.map((f) => f.lo)],
          lineStyle: { width: 0 }, symbol: "none", stack: "band",
          areaStyle: { color: "#00000000" },
        },
        {
          name: "Коридор-верх", type: "line",
          data: [...lastObs.map(() => null), ...forecast.map((f) => +(f.hi - f.lo).toFixed(4))],
          lineStyle: { width: 0 }, symbol: "none", stack: "band",
          areaStyle: { color: "#29b6f633" },
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [forecast, ts]);

  // Расширенный график динамики
  useEffect(() => {
    if (!chartRef.current || !ts.length) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: 600,
      tooltip: {
        trigger: "axis",
        backgroundColor: "#181d17ee",
        borderColor: "#2a3029",
        textStyle: { color: "#f2f4ec", fontSize: 12 },
      },
      legend: { textStyle: { color: "#a8b09f", fontSize: 11 }, top: 0, itemGap: 16 },
      grid: { left: 50, right: 50, bottom: 30, top: 40 },
      xAxis: {
        type: "category",
        data: ts.map((p) => String(p.date).slice(0, 10)),
        axisLine: { lineStyle: { color: "#2a3029" } },
        axisLabel: { color: "#a8b09f", fontSize: 10 },
      },
      yAxis: [
        {
          type: "value", name: "NDVI",
          nameTextStyle: { color: "#a8b09f", fontSize: 10 },
          axisLabel: { color: "#a8b09f", fontSize: 10 },
          splitLine: { lineStyle: { color: "#1e241c" } },
        },
        {
          type: "value", name: "мм",
          nameTextStyle: { color: "#a8b09f", fontSize: 10 },
          axisLabel: { color: "#a8b09f", fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        ...(showLayers.ndvi ? [{
          name: "NDVI", type: "line", data: ts.map((p) => p.ndvi_observed),
          smooth: true, symbol: "none",
          lineStyle: { width: 2.5, color: "#7cc46a" },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "#7cc46a33" },
              { offset: 1, color: "#7cc46a05" },
            ]),
          },
        }] : []),
        {
          name: "Норма", type: "line", data: ts.map((p) => p.ndvi_climatology),
          lineStyle: { type: "dashed", color: "#a8b09f", width: 1.5 },
          symbol: "none",
        },
        {
          name: "Осадки", type: "bar", yAxisIndex: 1,
          data: ts.map((p) => p.precipitation),
          itemStyle: { color: "#6aa9c444" },
          barWidth: "40%",
        },
        ...(showLayers.anomaly ? [{
          name: "Аномалия", type: "scatter",
          data: ts.filter((p) => p.anomaly).map((p) => [String(p.date).slice(0, 10), p.ndvi_observed]),
          symbolSize: 10,
          itemStyle: { color: "#e05c5c", borderColor: "#e05c5c88", borderWidth: 2 },
        }] : []),
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [ts, showLayers.ndvi, showLayers.anomaly]);

  function goBack() {
    if (leaving) return;
    setLeaving(true);
    // Уход обратно в чёрный — зеркально переходу туда
    setTimeout(() => router.push("/"), 450);
  }

  const crop = meta?.crop || "unknown";
  const area = meta?.area_ha != null ? `${meta.area_ha} га` : null;

  return (
    <div className={`field-page${entered && !leaving ? " entered" : ""}${leaving ? " leaving" : ""}`}>
      <header className="field-header">
        <button className="btn-secondary btn-sm" onClick={goBack}>← Карта</button>
        <div className="field-title">
          <span className="field-id">{id}</span>
          <span className="badge normal">{getCropRu(crop)}</span>
          {area && <span className="field-area">{area}</span>}
        </div>
        {!loading && !!kpi.current_ndvi && (
          <button className="btn-secondary btn-sm" onClick={downloadCSV}>⬇ CSV</button>
        )}
        {!loading && !!kpi.current_ndvi && (
          <span className={`badge ${level}`}>{LEVEL_RU[level] || level}</span>
        )}
      </header>

      <main className="field-body">
        {loading && <PipelineState />}
        {error && !loading && (
          <ErrorState text={error} onRetry={() => { setError(null); setLoading(true); const c = (meta as any)?.center; const o = c && c.length === 2 ? { lat: Number(c[0]), lon: Number(c[1]) } : {}; fetchAnalysis(id, regionId, o).then(setData).catch((e) => setError(`Анализ недоступен: ${e.message}.`)).finally(() => setLoading(false)); }} />
        )}
        {!loading && !error && !kpi.current_ndvi && (
          <EmptyState text="Нет данных для анализа этого поля." icon="◉" />
        )}

        {!loading && !!kpi.current_ndvi && (
          <>
            {!!(data?.sources || data?.stats) && (
              <section className="panel">
                <div className="panel-title">Конвейер данных · без ручной загрузки</div>
                <div className="pipeline-steps">
                  {[
                    ["Спутник", data?.sources?.satellite],
                    ["Погода", data?.sources?.weather],
                    ["Точек", data?.stats?.points != null ? String(data.stats.points) : null],
                    ["Восстановление", data?.sources?.restore],
                  ].filter(([, v]) => v).map(([label, v]) => (
                    <div key={label} className="pipeline-step">
                      <div className="pipeline-dot active" />
                      <span>{label}: <b>{v}</b></span>
                    </div>
                  ))}
                </div>
                <span className="pipeline-label">
                  Период {data?.stats?.date_min || "—"} — {data?.stats?.date_max || "—"}
                  {data?.stats?.gaps_filled != null && ` · закрыто пропусков: ${data.stats.gaps_filled}`}
                </span>
              </section>
            )}
            <section className="panel">
              <div className="panel-title">Ключевые показатели</div>
              <KPI data={kpi} />
              {stats && (
                <div className="stat-strip">
                  <div className="stat"><span className="stat-label">Период</span><span className="stat-value sm mono">{stats.period}</span></div>
                  <div className="stat"><span className="stat-label">Средний NDVI</span><span className="stat-value mono">{stats.mean}</span></div>
                  <div className="stat"><span className="stat-label">Мин – макс</span><span className="stat-value sm mono">{stats.min} – {stats.max}</span></div>
                  <div className="stat"><span className="stat-label">Осадки за сезон</span><span className="stat-value mono">{stats.precip} мм</span></div>
                  <div className="stat"><span className="stat-label">Дней с аномалией</span><span className="stat-value mono">{stats.anomDays} / {stats.points}</span></div>
                  <div className="stat"><span className="stat-label" title="Суммарный дефицит NDVI относительно нормы за сезон (эвристика)">Недобор биомассы</span><span className="stat-value mono">{stats.deficit}%</span></div>
                </div>
              )}
            </section>

            <section className="panel">
              <div className="panel-title-row">
                <div className="panel-title">Динамика вегетации · {stats?.points || 0} точек</div>
                <div className="mini-toggles">
                  <label><input type="checkbox" checked={showLayers.ndvi} onChange={() => setShowLayers((s) => ({ ...s, ndvi: !s.ndvi }))} /> NDVI</label>
                  <label><input type="checkbox" checked={showLayers.anomaly} onChange={() => setShowLayers((s) => ({ ...s, anomaly: !s.anomaly }))} /> Аномалии</label>
                </div>
              </div>
              <div className="chart-container">
                <div ref={chartRef} className="chart-main" style={{ width: "100%", height: 340 }} />
              </div>
            </section>

            {!!forecast.length && (
              <section className="panel">
                <div className="panel-title-row">
                  <div className="panel-title">Прогноз NDVI · {forecast.length} шагов (эксперимент)</div>
                </div>
                {fcSummary && (
                  <div className="reco">
                    <div className="reco-title">Вывод: {fcSummary.dir}</div>
                    <div className="reco-text">
                      {fcSummary.d > 0 ? "+" : ""}{fcSummary.d.toFixed(3)} NDVI за ~{fcSummary.days} дн.,
                      коридор ±{(fcSummary.unc / 2).toFixed(3)} к концу срока.
                      {fcSummary.dir === "снижение" ? " Стоит проверить поле раньше планового объезда." : fcSummary.dir === "рост" ? " Динамика положительная." : " Резких изменений не ожидается."}
                    </div>
                  </div>
                )}
                <div className="chart-container">
                  <div ref={fcRef} className="chart-forecast" style={{ width: "100%", height: 220 }} />
                </div>
                <div className="compare-table-wrap">
                  <table className="compare-table">
                    <thead><tr><th>Дата</th><th>NDVI</th><th>Мин</th><th>Макс</th></tr></thead>
                    <tbody>
                      {forecast.map((f) => (
                        <tr key={f.date}>
                          <td className="mono">{f.date.slice(0, 10)}</td>
                          <td className="mono">{f.ndvi.toFixed(3)}</td>
                          <td className="mono">{f.lo.toFixed(3)}</td>
                          <td className="mono">{f.hi.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <span className="pipeline-label">Эвристика «тренд + сезонность», коридор ±σ — для планирования выездов, не диагноз.</span>
              </section>
            )}

            <div className="field-grid">
              <section className="panel">
                <div className="panel-title">Аномалии · {(data?.anomalies || []).length}</div>
                {!(data?.anomalies || []).length && (
                  <div className="all-clear"><span className="all-clear-icon">●</span>Аномалий не выявлено — поле в норме.</div>
                )}
                {(data?.anomalies || []).map((a: any, i: number) => (
                  <div key={i} className="anomaly-row">
                    <span className={`badge ${a.level}`}>{LEVEL_RU[a.level] || a.level}</span>
                    <span className="anomaly-mini-period">{fmtDate(a.start_date)} — {fmtDate(a.end_date)}</span>
                    <span className="anomaly-kind">{KIND_RU[a.kind] || a.kind || ""}{spanDays(a) ? ` · ${spanDays(a)}` : ""}</span>
                    <span className="anomaly-mini-score">оценка {a.anomaly_score}</span>
                    {a.recovered && <span className="recovered-chip">✓ восстановление</span>}
                  </div>
                ))}
                {(data?.explanations || []).map((ex: any, i: number) => (
                  <AnomalyCard key={`ex-${i}`} explanation={ex} />
                ))}
              </section>

              <section className="panel">
                <div className="panel-title">Детали и рекомендации</div>
                <div className="detail-rows">
                  <div className="detail-row"><span>Оценка аномальности</span><b className="mono">{kpi.anomaly_score ?? "—"}</b></div>
                  <div className="detail-row"><span>Качество данных</span><b className="mono">{kpi.data_quality ?? "—"}{typeof kpi.data_quality === "number" && kpi.data_quality <= 1 ? " (доля)" : "%"}</b></div>
                  <div className="detail-row"><span>Спутник</span><b>{data?.sources?.satellite || "—"}</b></div>
                  <div className="detail-row"><span>Погода</span><b>{data?.sources?.weather || "—"}</b></div>
                  <div className="detail-row"><span>Восстановление ряда</span><b>{data?.sources?.restore || "—"}</b></div>
                </div>
                <div className="reco">
                  <div className="reco-title">Рекомендация</div>
                  <div className="reco-text">{RECOMMEND[level] || RECOMMEND.normal}</div>
                </div>
                {!!(data?.warnings || []).length && (
                  <div className="warn-block">
                    {(data?.warnings || []).map((w: string, i: number) => (
                      <div key={i} className="info-note">ℹ {w}</div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
