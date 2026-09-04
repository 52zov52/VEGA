"use client";
import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Field = { id: string; region_id: string; crop: string; area_ha: number; center: [number, number] };

export default function Page() {
  const mapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const [regions, setRegions] = useState<any[]>([]);
  const [regionId, setRegionId] = useState("rostov");
  const [fields, setFields] = useState<Field[]>([]);
  const [fieldId, setFieldId] = useState<string>("");
  const [analysis, setAnalysis] = useState<any>(null);
  const [ts, setTs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState({ agriculture: true, ndvi: true, anomaly: true });

  useEffect(() => {
    fetch(`${API}/api/regions/search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: "" }) })
      .then((r) => r.json()).then((j) => setRegions(j.regions || [])).catch(() => setRegions([]));
  }, []);

  useEffect(() => {
    fetch(`${API}/api/regions/${regionId}/fields?limit=60`).then((r) => r.json())
      .then((j) => { setFields(j.fields || []); if (j.fields?.length) setFieldId(j.fields[0].id); })
      .catch(() => setError("Не удалось загрузить поля региона"));
  }, [regionId]);

  // Карта: главный элемент интерфейса (§4). MapLibre + подсветка аномальных участков.
  useEffect(() => {
    let map: any;
    (async () => {
      const maplibre = await import("maplibre-gl");
      await import("maplibre-gl/dist/maplibre-gl.css");
      if (!mapRef.current || (mapRef.current as any)._vega) return;
      (mapRef.current as any)._vega = true;
      map = new maplibre.Map({
        container: mapRef.current!, style: "https://demotiles.maplibre.org/style.json",
        center: [39.7, 47.2], zoom: 7,
      });
      (window as any).__vegaMap = map;
    })();
    return () => { try { map?.remove(); } catch {} };
  }, []);

  // Маркеры полей
  useEffect(() => {
    const map = (window as any).__vegaMap;
    if (!map || !fields.length) return;
    const docs: any[] = [];
    (async () => {
      const maplibre = await import("maplibre-gl");
      fields.slice(0, 60).forEach((f) => {
        const el = document.createElement("button");
        el.textContent = "▣";
        el.title = `${f.id} · ${f.crop}`;
        el.style.cssText = "background:none;border:0;font-size:18px;cursor:pointer;color:#7cc46a";
        el.onclick = () => setFieldId(f.id);
        const m = new maplibre.Marker({ element: el }).setLngLat([f.center[1], f.center[0]]).addTo(map);
        docs.push(m);
      });
      map.flyTo({ center: [fields[0].center[1], fields[0].center[0]], zoom: 9 });
    })();
    return () => { docs.forEach((m) => m.remove()); };
  }, [fields]);

  // График: observed + climatology + anomaly zones + precipitation (§21)
  useEffect(() => {
    if (!chartRef.current || !ts.length) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#a8b09f" } },
      xAxis: { type: "category", data: ts.map((p) => p.date) },
      yAxis: [{ type: "value", name: "NDVI" }, { type: "value", name: "мм" }],
      series: [
        { name: "NDVI", type: "line", data: ts.map((p) => p.ndvi_observed), smooth: true, lineStyle: { width: 2 } },
        { name: "Норма", type: "line", data: ts.map((p) => p.ndvi_climatology), lineStyle: { type: "dashed" } },
        { name: "Осадки", type: "bar", yAxisIndex: 1, data: ts.map((p) => p.precipitation), opacity: 0.4 },
        {
          name: "Аномалия", type: "scatter", data: ts.filter((p) => p.anomaly).map((p) => [p.date, p.ndvi_observed]),
          symbolSize: 10, itemStyle: { color: "#e05c5c" },
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [ts]);

  async function runAnalyze(demo = false) {
    setLoading(true); setError(null);
    try {
      const pid = demo ? "AOI-00001" : fieldId || "AOI-00001";
      const r = await fetch(`${API}/api/analyze`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ polygon_id: pid, region_id: regionId, start: "2023-05-01", end: "2023-09-30", lat: 47.2, lon: 39.7 }),
      });
      if (!r.ok) throw new Error(`API ${r.status}`);
      const j = await r.json();
      setAnalysis(j);
      const t = await fetch(`${API}/api/analyze/${j.analysis_id}/timeseries`).then((x) => x.json());
      setTs(t.timeseries || []);
      const a = await fetch(`${API}/api/analyze/${j.analysis_id}/anomalies`).then((x) => x.json());
      const e = await fetch(`${API}/api/analyze/${j.analysis_id}/explanation`).then((x) => x.json());
      setAnalysis((prev: any) => ({ ...prev, anomalies: a.anomalies, explanations: e.explanations }));
    } catch (err: any) {
      setError(`Анализ недоступен: ${err.message}. Проверьте, что backend запущен.`);
    } finally {
      setLoading(false);
    }
  }

  const kpi = analysis?.kpi || {};
  const expl = analysis?.explanations?.[0];

  return (
    <div>
      <header style={{ display: "flex", gap: 12, alignItems: "center", padding: "10px 16px" }}>
        <b>VEGA</b><span style={{ color: "var(--text-muted)" }}>Vegetation Intelligence</span>
        <span style={{ flex: 1 }} />
        <button className="secondary" onClick={() => runAnalyze(true)} disabled={loading}>Demo mode</button>
        <button onClick={() => runAnalyze(false)} disabled={loading}>{loading ? "Анализ…" : "Run live analysis"}</button>
      </header>
      <div className="layout">
        <aside className="sidebar" aria-label="Регионы и поля">
          <label>Регион</label>
          <select value={regionId} onChange={(e) => setRegionId(e.target.value)}>
            {(regions.length ? regions : [{ id: "rostov", name: "Rostov region" }]).map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
          <h4>Поля ({fields.length})</h4>
          {fields.slice(0, 12).map((f) => (
            <div key={f.id} className="card" style={{ border: f.id === fieldId ? "1px solid var(--accent-vegetation)" : "none" }}>
              <b>{f.id}</b> <span className="badge normal">{f.crop}</span>
              <div style={{ color: "var(--text-muted)" }}>{f.area_ha} га</div>
              <button className="secondary" onClick={() => setFieldId(f.id)}>Выбрать</button>
            </div>
          ))}
          <h4>Слои</h4>
          {(Object.keys(layers) as (keyof typeof layers)[]).map((k) => (
            <label key={k} style={{ display: "block" }}>
              <input type="checkbox" checked={layers[k]} onChange={() => setLayers({ ...layers, [k]: !layers[k] })} /> {k}
            </label>
          ))}
        </aside>
        <main className="map-wrap" aria-label="Карта">
          <div id="map" ref={mapRef} role="application" aria-label="Карта полей" />
          {!fields.length && <div className="skeleton">Загрузка карты…</div>}
        </main>
        <aside className="panel" aria-label="Анализ поля">
          {error && <div className="card" role="alert">⚠ {error}</div>}
          <h3>Выбранное поле: {fieldId || "—"}</h3>
          {loading && <div className="skeleton">Сбор данных → ряд → ML → аномалии…</div>}
          {!!kpi.current_ndvi && (
            <>
              <div className="kpi">
                <div>NDVI<b>{kpi.current_ndvi}</b></div>
                <div>Отклонение<b>{kpi.season_deviation_pct}%</b></div>
                <div>Риск<b>{kpi.level}</b></div>
                <div>Качество<b>{kpi.data_quality}</b></div>
              </div>
              <div ref={chartRef} style={{ height: 280 }} role="img" aria-label="Временной ряд NDVI" />
              {analysis?.anomalies?.slice(0, 3).map((a: any, i: number) => (
                <div key={i} className="card">
                  <span className={`badge ${a.level}`}>{a.level}</span> {a.start_date} — {a.end_date}
                  <div>score {a.anomaly_score} · z {a.zscore} · {a.deviation_pct}%</div>
                </div>
              ))}
              {expl && (
                <div className="card" aria-label="Почему аномалия">
                  <h4>WHY IS THIS ANOMALY?</h4>
                  <p>{expl.headline}</p>
                  {expl.factors.map((f: any) => (
                    <div key={f.signal}>{f.signal} {f.delta_pct > 0 ? "+" : ""}{f.delta_pct}% ({f.strength})
                      <div className="bar"><i style={{ width: `${Math.min(100, Math.abs(f.delta_pct))}%` }} /></div>
                    </div>
                  ))}
                  <p><b>Вывод:</b> {expl.likely_cause}</p>
                  <p>Уверенность: {Math.round(expl.confidence * 100)}%</p>
                  <p style={{ color: "var(--text-muted)" }}>{expl.narrative}</p>
                </div>
              )}
              {analysis?.warnings?.map((w: string, i: number) => (
                <div key={i} style={{ color: "var(--text-muted)", fontSize: 12 }}>ℹ {w}</div>
              ))}
            </>
          )}
          {!kpi.current_ndvi && !loading && <p style={{ color: "var(--text-muted)" }}>Выберите поле и нажмите «Run live analysis». Данные соберутся автоматически.</p>}
        </aside>
      </div>
    </div>
  );
}
