"use client";
import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import * as echarts from "echarts";
import dynamic from "next/dynamic";
import { MapPin, Layers, Pencil, Trash2, BarChart3, Play } from "lucide-react";
import Modal from "../components/Modal";
import KPI from "../components/KPI";
import AnomalyCard from "../components/AnomalyCard";
import { LoadingSkeleton, EmptyState, ErrorState, PipelineState } from "../components/UIStates";

const Globe = dynamic(() => import("../components/Globe"), { ssr: false });
import { getCropRu } from "../components/Globe";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Field = { id: string; region_id: string; crop: string; area_ha: number; center: [number, number]; geometry?: any };
type SavedPoly = { id: string; name: string; geometry: any };

const REGION_COORDS: Record<string, [number, number]> = {
  rostov: [47.2, 39.7],
  krasnodar: [45.0, 38.9],
  voronezh: [51.6, 39.2],
};

const LAYER_RU: Record<string, string> = {
  agriculture: "Контуры полей",
  ndvi: "Заливка NDVI",
  anomaly: "Метки полей",
};

const LEVEL_RU: Record<string, string> = {
  normal: "Норма",
  watch: "Наблюдение",
  stress: "Стресс",
  critical: "Критично",
};

// Свой полигон -> то же поле для карты: центр и площадь считаем по bbox геометрии
function fieldFromSaved(p: SavedPoly): Field {
  const ring: [number, number][] = p.geometry?.coordinates?.[0] || [];
  if (!ring.length) {
    return { id: p.id, region_id: "", crop: "unknown", area_ha: 0, center: [47.2, 39.7], geometry: p.geometry };
  }
  let minLng = 180, maxLng = -180, minLat = 90, maxLat = -90;
  for (const [lng, lat] of ring) {
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }
  const avgLat = ((minLat + maxLat) / 2) * Math.PI / 180;
  const areaHa = Math.max(0, maxLat - minLat) * 111.32 * Math.max(0, maxLng - minLng) * 111.32 * Math.cos(avgLat) * 100;
  return {
    id: p.id,
    region_id: "",
    crop: "unknown",
    area_ha: Math.round(areaHa * 10) / 10,
    center: [(minLat + maxLat) / 2, (minLng + maxLng) / 2],
    geometry: p.geometry,
  };
}

export default function Page() {
  const chartRef = useRef<HTMLDivElement>(null);
  const [regions, setRegions] = useState<any[]>([]);
  const [regionQuery, setRegionQuery] = useState("");
  const [regionId, setRegionId] = useState("rostov");
  const [fields, setFields] = useState<Field[]>([]);
  const [fieldsState, setFieldsState] = useState<"idle" | "loading" | "empty" | "error">("idle");
  const [fieldId, setFieldId] = useState<string>("");
  const [analysis, setAnalysis] = useState<any>(null);
  const [ts, setTs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState({ agriculture: true, ndvi: true, anomaly: true });
  const [drawMode, setDrawMode] = useState(false);
  const [vertices, setVertices] = useState<[number, number][]>([]);
  const [saved, setSaved] = useState<SavedPoly[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareData, setCompareData] = useState<any[]>([]);
  const [comparing, setComparing] = useState(false);
  const [globeFlyTo, setGlobeFlyTo] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [selectedField, setSelectedField] = useState<Field | null>(null);

  async function loadRegions(q = "") {
    try {
      const r = await fetch(`${API}/api/regions/search`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q }),
      });
      setRegions((await r.json()).regions || []);
    } catch { setRegions([]); }
  }

  async function loadSaved() {
    try {
      const r = await fetch(`${API}/api/polygons`).then((x) => x.json());
      setSaved(r.polygons || []);
    } catch { /* backend недоступен */ }
  }

  useEffect(() => { loadRegions(""); loadSaved(); }, []);

  useEffect(() => {
    setFieldsState("loading");
    fetch(`${API}/api/regions/${regionId}/fields?limit=60`).then((r) => r.json())
      .then((j) => {
        const list = j.fields || [];
        setFields(list);
        setFieldsState(list.length ? "idle" : "empty");
        if (list.length && !fieldId) setFieldId(list[0].id);
      })
      .catch(() => setFieldsState("error"));
  }, [regionId]);

  const savedFields = useMemo<Field[]>(() => saved.map(fieldFromSaved), [saved]);
  const globeFields = useMemo(() => [...fields, ...savedFields], [fields, savedFields]);

  const handleFieldSelect = useCallback((id: string) => {
    setFieldId(id);
    const field = globeFields.find((f) => f.id === id);
    setSelectedField(field || null);
    setGlobeFlyTo((n) => n + 1);
  }, [globeFields]);

  // Клик по глобусу в режиме рисования -> новая вершина полигона
  const handleDrawPoint = useCallback((lng: number, lat: number) => {
    setVertices((v) => [...v, [lng, lat]]);
  }, []);

  async function finishDrawing() {
    if (vertices.length < 3) { setError("Нужно минимум 3 точки."); return; }
    const geometry = { type: "Polygon", coordinates: [[...vertices, vertices[0]]] };
    try {
      const r = await fetch(`${API}/api/polygons`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ region_id: regionId, geometry }),
      });
      const poly = await r.json();
      setSaved((s) => [...s, poly]);
      const field = fieldFromSaved(poly);
      setFieldId(field.id);
      setSelectedField(field);
      setGlobeFlyTo((n) => n + 1);
      setVertices([]); setDrawMode(false);
    } catch { setError("Не удалось сохранить полигон."); }
  }

  async function deleteSaved(id: string) {
    try {
      await fetch(`${API}/api/polygons/${id}`, { method: "DELETE" });
      setSaved((s) => s.filter((p) => p.id !== id));
    } catch { setError("Не удалось удалить полигон."); }
  }

  // Анализ из попапа на глобусе
  async function handleAnalyzeField(pid: string) {
    setFieldId(pid);
    const field = globeFields.find((f) => f.id === pid);
    setSelectedField(field || null);
    setGlobeFlyTo((n) => n + 1);
    setLoading(true); setError(null);
    try {
      const full = await fetchAnalysis(pid);
      setAnalysis(full);
      setTs(full.ts);
      setModalOpen(true);
    } catch (err: any) {
      setError(`Анализ недоступен: ${err.message}.`);
    } finally {
      setLoading(false);
    }
  }

  // График
  useEffect(() => {
    if (!chartRef.current || !ts.length) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#181d17ee",
        borderColor: "#2a3029",
        textStyle: { color: "#f2f4ec", fontSize: 12 },
      },
      legend: {
        textStyle: { color: "#a8b09f", fontSize: 11 },
        top: 0,
        itemGap: 16,
      },
      grid: { left: 50, right: 50, bottom: 30, top: 40 },
      xAxis: {
        type: "category", data: ts.map((p) => p.date),
        axisLine: { lineStyle: { color: "#2a3029" } },
        axisLabel: { color: "#a8b09f", fontSize: 10 },
      },
      yAxis: [
        {
          type: "value", name: "NDVI",
          nameTextStyle: { color: "#a8b09f", fontSize: 10 },
          axisLine: { lineStyle: { color: "#2a3029" } },
          axisLabel: { color: "#a8b09f", fontSize: 10 },
          splitLine: { lineStyle: { color: "#1e241c" } },
        },
        {
          type: "value", name: "мм",
          nameTextStyle: { color: "#a8b09f", fontSize: 10 },
          axisLine: { lineStyle: { color: "#2a3029" } },
          axisLabel: { color: "#a8b09f", fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        ...(layers.ndvi ? [{
          name: "NDVI", type: "line", data: ts.map((p) => p.ndvi_observed),
          smooth: true, symbol: "none",
          lineStyle: { width: 2.5, color: "#7cc46a" },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "#7cc46a33" },
            { offset: 1, color: "#7cc46a05" },
          ]) },
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
        ...(layers.anomaly ? [{
          name: "Аномалия", type: "scatter",
          data: ts.filter((p) => p.anomaly).map((p) => [p.date, p.ndvi_observed]),
          symbolSize: 10,
          itemStyle: { color: "#e05c5c", borderColor: "#e05c5c88", borderWidth: 2 },
        }] : []),
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [ts, layers.ndvi, layers.anomaly]);

  async function fetchAnalysis(pid: string) {
    const r = await fetch(`${API}/api/analyze`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ polygon_id: pid, region_id: regionId, start: "2023-05-01", end: "2023-09-30", lat: 47.2, lon: 39.7 }),
    });
    if (!r.ok) throw new Error(`API ${r.status}`);
    const j = await r.json();
    const t = await fetch(`${API}/api/analyze/${j.analysis_id}/timeseries`).then((x) => x.json());
    const a = await fetch(`${API}/api/analyze/${j.analysis_id}/anomalies`).then((x) => x.json());
    const e = await fetch(`${API}/api/analyze/${j.analysis_id}/explanation`).then((x) => x.json());
    return { ...j, ts: t.timeseries || [], anomalies: a.anomalies, explanations: e.explanations };
  }

  async function runAnalyze(demo = false) {
    setLoading(true); setError(null);
    try {
      const pid = demo ? "AOI-00001" : fieldId || "AOI-00001";
      const full = await fetchAnalysis(pid);
      setAnalysis(full);
      setTs(full.ts);
      setModalOpen(true);
    } catch (err: any) {
      setError(`Анализ недоступен: ${err.message}.`);
    } finally {
      setLoading(false);
    }
  }

  async function runCompare() {
    if (compareIds.length < 2) { setError("Для сравнения выберите 2–5 полей."); return; }
    setComparing(true); setError(null);
    try {
      const rows = [];
      for (const pid of compareIds.slice(0, 5)) rows.push({ id: pid, ...(await fetchAnalysis(pid)) });
      setCompareData(rows);
      setCompareOpen(true);
    } catch (e: any) {
      setError(`Сравнение не удалось: ${e.message}`);
    } finally {
      setComparing(false);
    }
  }

  function toggleCompare(id: string) {
    setCompareIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(0, 5));
  }

  const kpi = analysis?.kpi || {};
  const expl = analysis?.explanations?.[0];

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <span className="header-logo">◇</span>
          <span className="header-title">VEGA</span>
          <span className="header-sub">Мониторинг вегетации</span>
        </div>
      </header>

      {/* Layout: sidebar + globe (без правой панели) */}
      <div className="layout layout--no-panel">
        {/* Sidebar */}
        <aside className="sidebar">
          <div className="sidebar-section">
            <label className="label" htmlFor="region-search">Регион</label>
            <input
              id="region-search"
              className="input"
              placeholder="Поиск региона…"
              value={regionQuery}
              onChange={(e) => { setRegionQuery(e.target.value); loadRegions(e.target.value); }}
            />
            <select
              className="input select"
              value={regionId}
              onChange={(e) => setRegionId(e.target.value)}
            >
              {(regions.length ? regions : [
                { id: "rostov", name: "Ростовская область" },
                { id: "krasnodar", name: "Краснодарский край" },
                { id: "voronezh", name: "Воронежская область" },
              ]).map((r: any) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </div>

          <div className="sidebar-section">
            <div className="sidebar-section-header">
              <span className="label">Поля</span>
              <span className="badge-count">{fields.length}</span>
            </div>
            {fieldsState === "loading" && <LoadingSkeleton text="Загрузка контуров…" />}
            {fieldsState === "empty" && <EmptyState text="Контуры не найдены. Нарисуйте свой полигон." icon="◇" />}
            {fieldsState === "error" && (
              <ErrorState text="Не удалось загрузить поля." onRetry={() => setRegionId((r) => r)} />
            )}
            <div className="field-list">
              {fields.slice(0, 20).map((f) => (
                <div
                  key={f.id}
                  className={`field-card ${f.id === fieldId ? "selected" : ""}`}
                  onClick={() => handleFieldSelect(f.id)}
                >
                  <div className="field-card-header">
                    <span className="field-card-id">{f.id}</span>
                    <span className="badge normal">{getCropRu(f.crop)}</span>
                  </div>
                  <span className="field-card-area">{f.area_ha} га</span>
                  <label className="field-compare" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={compareIds.includes(f.id)}
                      onChange={() => toggleCompare(f.id)}
                    />
                    <span>сравнить</span>
                  </label>
                </div>
              ))}
            </div>
            {compareIds.length >= 2 && (
              <button className="btn-secondary btn-full" onClick={runCompare} disabled={comparing}>
                {comparing ? "Сравнение…" : `Сравнить (${compareIds.length})`}
              </button>
            )}
          </div>

          <div className="sidebar-section">
            <span className="label">Свой полигон</span>
            {!drawMode
              ? <button className="btn-secondary btn-full" onClick={() => { setDrawMode(true); setVertices([]); }}>✏ Нарисовать</button>
              : (
                <div className="draw-info">
                  <span>Точек: {vertices.length}. Нужно ≥ 3.</span>
                  <div className="draw-actions">
                    <button className="btn-primary btn-sm" onClick={finishDrawing} disabled={vertices.length < 3}>Готово</button>
                    <button className="btn-secondary btn-sm" onClick={() => { setDrawMode(false); setVertices([]); }}>Отмена</button>
                  </div>
                </div>
              )}
          </div>

          {saved.length > 0 && (
            <div className="sidebar-section">
              <span className="label">Сохранённые ({saved.length})</span>
              {saved.map((p) => (
                <div key={p.id} className="field-card">
                  <span className="field-card-id">{p.id}</span>
                  <div className="draw-actions">
                    <button className="btn-secondary btn-sm" onClick={() => handleFieldSelect(p.id)}>Выбрать</button>
                    <button className="btn-ghost btn-sm" onClick={() => deleteSaved(p.id)}>Удалить</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="sidebar-section">
            <span className="label">Слои</span>
            {(Object.keys(layers) as (keyof typeof layers)[]).map((k) => (
              <label key={k} className="layer-toggle">
                <input type="checkbox" checked={layers[k]} onChange={() => setLayers({ ...layers, [k]: !layers[k] })} />
                <span>{LAYER_RU[k] || k}</span>
              </label>
            ))}
          </div>
        </aside>

        {/* Globe */}
        <main className={drawMode ? "globe-wrap drawing" : "globe-wrap"}>
          <Globe
            fields={globeFields}
            selectedId={fieldId}
            onSelect={handleFieldSelect}
            onAnalyze={handleAnalyzeField}
            regionCenter={REGION_COORDS[regionId] || [47.2, 39.7]}
            flyToTrigger={globeFlyTo}
            drawMode={drawMode}
            onDrawPoint={handleDrawPoint}
            layers={layers}
          />
          {drawMode && (
            <div className="draw-overlay">
              ✏ Кликните {Math.max(0, 3 - vertices.length)}+ точек на карте
            </div>
          )}
        </main>
      </div>

      {/* Модальное окно анализа */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={selectedField ? `${selectedField.id} · ${getCropRu(selectedField.crop)}` : "Анализ"}>
        {loading && <PipelineState />}
        {error && <ErrorState text={error} />}
        {!loading && !kpi.current_ndvi && (
          <EmptyState text="Нажмите «Анализ поля» для сбора данных." icon="◉" />
        )}
        {!!kpi.current_ndvi && (
          <>
            <KPI data={kpi} />
            <div className="chart-container">
              <div ref={chartRef} style={{ width: "100%", height: 280 }} />
            </div>
            {analysis?.anomalies?.slice(0, 3).map((a: any, i: number) => (
              <div key={i} className="anomaly-mini">
                <span className={`badge ${a.level}`}>{a.level}</span>
                <span className="anomaly-mini-period">{a.start_date} — {a.end_date}</span>
                <span className="anomaly-mini-score">оценка {a.anomaly_score}</span>
              </div>
            ))}
            {!analysis?.anomalies?.length && (
              <div className="all-clear">
                <span className="all-clear-icon">●</span>
                Аномалий не выявлено — поле в норме.
              </div>
            )}
            {expl && <AnomalyCard explanation={expl} />}
            {analysis?.warnings?.map((w: string, i: number) => (
              <div key={i} className="info-note">ℹ {w}</div>
            ))}
          </>
        )}
      </Modal>

      {/* Модальное окно сравнения полей */}
      <Modal open={compareOpen} onClose={() => setCompareOpen(false)} title={`Сравнение полей (${compareData.length})`}>
        {comparing && <PipelineState />}
        {!comparing && !compareData.length && (
          <EmptyState text="Нет данных для сравнения." icon="◇" />
        )}
        {!comparing && !!compareData.length && (
          <div className="compare-table-wrap">
            <table className="compare-table">
              <thead>
                <tr>
                  <th>Поле</th>
                  <th>Культура</th>
                  <th>NDVI</th>
                  <th>Откл., %</th>
                  <th>Риск</th>
                  <th>Качество</th>
                </tr>
              </thead>
              <tbody>
                {compareData.map((row: any) => {
                  const f = globeFields.find((x) => x.id === row.id);
                  const level = row.kpi?.level || "normal";
                  return (
                    <tr key={row.id} className={row.id === fieldId ? "current" : ""}>
                      <td className="mono">{row.id}</td>
                      <td>{f ? getCropRu(f.crop) : "—"}</td>
                      <td className="mono">{row.kpi?.current_ndvi ?? "—"}</td>
                      <td className="mono">{row.kpi?.season_deviation_pct ?? "—"}</td>
                      <td><span className={`badge ${level}`}>{LEVEL_RU[level] || level}</span></td>
                      <td className="mono">{row.kpi?.data_quality ?? "—"}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Modal>
    </div>
  );
}
