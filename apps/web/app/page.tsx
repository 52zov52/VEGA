"use client";
import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Field = { id: string; region_id: string; crop: string; area_ha: number; center: [number, number] };
type SavedPoly = { id: string; name: string; geometry: any };

const LEVEL_COLOR: Record<string, string> = {
  critical: "#e05c5c",
  stress: "#e0a83c",
  watch: "#6aa9c4",
  normal: "#7cc46a",
};

export default function Page() {
  const mapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const compareRef = useRef<HTMLDivElement>(null);
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
  // Рисование полигона (§4): режим + вершины + сохранённые
  const [drawMode, setDrawMode] = useState(false);
  const [vertices, setVertices] = useState<[number, number][]>([]);
  const [saved, setSaved] = useState<SavedPoly[]>([]);
  // Сравнение полей (§23)
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareData, setCompareData] = useState<any[]>([]);
  const [comparing, setComparing] = useState(false);

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
    } catch { /* backend недоступен — покажем пустой список, а не 500 */ }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regionId]);

  // Карта: главный элемент интерфейса (§4). MapLibre + подсветка аномальных участков.
  useEffect(() => {
    let map: any;
    let cancelled = false;
    (async () => {
      const maplibre = await import("maplibre-gl");
      await import("maplibre-gl/dist/maplibre-gl.css");
      if (!mapRef.current || (mapRef.current as any)._vega || cancelled) return;
      (mapRef.current as any)._vega = true;
      map = new maplibre.Map({
        container: mapRef.current!, style: "https://demotiles.maplibre.org/style.json",
        center: [39.7, 47.2], zoom: 7,
      });
      (window as any).__vegaMap = map;
      map.on("click", (e: any) => {
        // В режиме рисования клики ставят вершины вместо выбора поля.
        const ev = new CustomEvent("vega-map-click", { detail: [e.lngLat.lng, e.lngLat.lat] });
        window.dispatchEvent(ev);
      });
    })();
    return () => { cancelled = true; };
  }, []);

  // Клики карты -> вершины рисуемого полигона
  useEffect(() => {
    if (!drawMode) return;
    const onClick = (e: Event) => {
      const [lng, lat] = (e as CustomEvent).detail as [number, number];
      setVertices((v) => [...v, [lng, lat]]);
    };
    window.addEventListener("vega-map-click", onClick);
    return () => window.removeEventListener("vega-map-click", onClick);
  }, [drawMode]);

  // Маркеры полей + heatmap-подсветка по уровню риска
  useEffect(() => {
    const map = (window as any).__vegaMap;
    if (!map || !fields.length) return;
    const markers: any[] = [];
    let cancelled = false;
    (async () => {
      const maplibre = await import("maplibre-gl");
      if (cancelled) return;
      if (!layers.agriculture) return;
      fields.slice(0, 60).forEach((f) => {
        const el = document.createElement("button");
        el.textContent = "▣";
        el.title = `${f.id} · ${f.crop}`;
        const isSel = f.id === fieldId;
        el.style.cssText = `background:none;border:0;font-size:${isSel ? 24 : 18}px;cursor:pointer;color:${isSel ? "#ffffff" : "#7cc46a"};${isSel ? "text-shadow:0 0 8px #7cc46a;" : ""}`;
        el.setAttribute("aria-label", `Выбрать поле ${f.id}`);
        el.onclick = () => setFieldId(f.id);
        markers.push(new maplibre.Marker({ element: el }).setLngLat([f.center[1], f.center[0]]).addTo(map));
      });
      map.flyTo({ center: [fields[0].center[1], fields[0].center[0]], zoom: 9 });
    })();
    return () => { cancelled = true; markers.forEach((m) => m.remove()); };
  }, [fields, fieldId, layers.agriculture]);

  // Слой рисуемого полигона
  useEffect(() => {
    const map = (window as any).__vegaMap;
    if (!map || vertices.length < 2) return;
    const coords = [...vertices, vertices[0]];
    const id = "vega-draw";
    const geo = { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [coords] } };
    if (map.getSource(id)) (map.getSource(id) as any).setData(geo);
    else {
      map.addSource(id, { type: "geojson", data: geo });
      map.addLayer({ id, type: "fill", source: id, paint: { "fill-color": "#7cc46a", "fill-opacity": 0.3 } });
    }
    return () => { /* слой живёт до завершения рисования */ };
  }, [vertices]);

  function clearDrawLayer() {
    const map = (window as any).__vegaMap;
    try { if (map?.getLayer("vega-draw")) map.removeLayer("vega-draw"); } catch {}
    try { if (map?.getSource("vega-draw")) map.removeSource("vega-draw"); } catch {}
  }

  async function finishDrawing() {
    if (vertices.length < 3) { setError("Нужно минимум 3 точки: кликайте по карте."); return; }
    const geometry = { type: "Polygon", coordinates: [[...vertices, vertices[0]]] };
    try {
      const r = await fetch(`${API}/api/polygons`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ region_id: regionId, geometry }),
      });
      const poly = await r.json();
      setSaved((s) => [...s, poly]);
      setFieldId(poly.id);
      setVertices([]); setDrawMode(false); clearDrawLayer();
    } catch { setError("Не удалось сохранить полигон: backend недоступен."); }
  }

  async function deleteSaved(id: string) {
    try {
      await fetch(`${API}/api/polygons/${id}`, { method: "DELETE" });
      setSaved((s) => s.filter((p) => p.id !== id));
    } catch { setError("Не удалось удалить полигон."); }
  }

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
        ...(layers.ndvi ? [{ name: "NDVI", type: "line", data: ts.map((p) => p.ndvi_observed), smooth: true, lineStyle: { width: 2, color: "#7cc46a" } }] : []),
        { name: "Норма", type: "line", data: ts.map((p) => p.ndvi_climatology), lineStyle: { type: "dashed", color: "#a8b09f" } },
        { name: "Осадки", type: "bar", yAxisIndex: 1, data: ts.map((p) => p.precipitation), opacity: 0.4 },
        ...(layers.anomaly ? [{
          name: "Аномалия", type: "scatter",
          data: ts.filter((p) => p.anomaly).map((p) => [p.date, p.ndvi_observed]),
          symbolSize: 10, itemStyle: { color: "#e05c5c" },
        }] : []),
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [ts, layers.ndvi, layers.anomaly]);

  // Сравнительный график 2–5 полей (§23)
  useEffect(() => {
    if (!compareRef.current || !compareData.length) return;
    const chart = echarts.init(compareRef.current);
    const dates = compareData[0]?.ts.map((p: any) => p.date) || [];
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#a8b09f" } },
      xAxis: { type: "category", data: dates },
      yAxis: { type: "value", name: "NDVI" },
      series: compareData.map((c: any, i: number) => ({
        name: c.id, type: "line", smooth: true,
        data: c.ts.map((p: any) => p.ndvi_observed),
        lineStyle: { color: ["#7cc46a", "#6aa9c4", "#e0a83c", "#e05c5c", "#b48ce0"][i % 5], width: 2 },
      })),
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.dispose(); };
  }, [compareData]);

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
    } catch (err: any) {
      setError(`Анализ недоступен: ${err.message}. Проверьте, что backend запущен (uvicorn apps.api.main:app --port 8000).`);
    } finally {
      setLoading(false);
    }
  }

  async function runCompare() {
    if (compareIds.length < 2) { setError("Для сравнения выберите 2–5 полей галочками."); return; }
    setComparing(true); setError(null);
    try {
      const rows = [];
      for (const pid of compareIds.slice(0, 5)) rows.push({ id: pid, ...(await fetchAnalysis(pid)) });
      setCompareData(rows);
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
    <div>
      <header style={{ display: "flex", gap: 12, alignItems: "center", padding: "10px 16px" }}>
        <b>VEGA</b><span style={{ color: "var(--text-muted)" }}>Vegetation Intelligence</span>
        <span style={{ flex: 1 }} />
        <button className="secondary" onClick={() => runAnalyze(true)} disabled={loading}>Demo mode</button>
        <button onClick={() => runAnalyze(false)} disabled={loading || !fieldId}>{loading ? "Анализ…" : "Run live analysis"}</button>
      </header>
      <div className="layout">
        <aside className="sidebar" aria-label="Регионы и поля">
          <label htmlFor="region-search">Поиск региона</label>
          <input id="region-search" placeholder="rostov…" value={regionQuery}
            onChange={(e) => { setRegionQuery(e.target.value); loadRegions(e.target.value); }} />
          <label htmlFor="region-select" style={{ marginTop: 8 }}>Регион</label>
          <select id="region-select" value={regionId} onChange={(e) => setRegionId(e.target.value)}>
            {(regions.length ? regions : [{ id: "rostov", name: "Rostov region" }, { id: "krasnodar", name: "Krasnodar region" }, { id: "voronezh", name: "Voronezh region" }]).map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
          <h4>Поля ({fields.length})</h4>
          {fieldsState === "loading" && <div className="skeleton" aria-label="Загрузка полей">Загрузка контуров…</div>}
          {fieldsState === "empty" && <p style={{ color: "var(--text-muted)" }}>Контуры не найдены. Нарисуйте свой полигон.</p>}
          {fieldsState === "error" && (
            <div className="card" role="alert">⚠ Не удалось загрузить поля.
              <button className="secondary" onClick={() => setRegionId((r) => r)}>Повторить</button>
            </div>
          )}
          {fields.slice(0, 12).map((f) => (
            <div key={f.id} className="card" style={{ border: f.id === fieldId ? "1px solid var(--accent-vegetation)" : "none" }}>
              <b>{f.id}</b> <span className="badge normal">{f.crop}</span>
              <div style={{ color: "var(--text-muted)" }}>{f.area_ha} га</div>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="secondary" onClick={() => setFieldId(f.id)} disabled={loading}>Выбрать</button>
                <label style={{ fontSize: 12 }}><input type="checkbox" checked={compareIds.includes(f.id)} onChange={() => toggleCompare(f.id)} /> сравнить</label>
              </div>
            </div>
          ))}
          <button className="secondary" onClick={runCompare} disabled={comparing || compareIds.length < 2}>
            {comparing ? "Сравнение…" : `Сравнить (${compareIds.length})`}
          </button>
          <h4>Свой полигон</h4>
          {!drawMode
            ? <button className="secondary" onClick={() => { setDrawMode(true); setVertices([]); }}>✏ Нарисовать полигон</button>
            : (
              <div className="card">
                <p>Кликайте по карте: точек {vertices.length}. Двойной клик/кнопка — завершить.</p>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={finishDrawing} disabled={vertices.length < 3}>Завершить</button>
                  <button className="secondary" onClick={() => { setDrawMode(false); setVertices([]); clearDrawLayer(); }}>Отмена</button>
                </div>
              </div>
            )}
          <h4>Сохранённые ({saved.length})</h4>
          {!saved.length && <p style={{ color: "var(--text-muted)", fontSize: 12 }}>Пока пусто.</p>}
          {saved.map((p) => (
            <div key={p.id} className="card">
              <b>{p.id}</b>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="secondary" onClick={() => setFieldId(p.id)}>Выбрать</button>
                <button className="secondary" onClick={() => deleteSaved(p.id)} aria-label={`Удалить ${p.id}`}>Удалить</button>
              </div>
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
          {!fields.length && fieldsState !== "error" && <div className="skeleton">Загрузка карты…</div>}
          {drawMode && <div className="card" style={{ position: "absolute", top: 8, left: 8, zIndex: 5 }}>✏ Режим рисования: кликните {Math.max(0, 3 - vertices.length)}+ точек</div>}
        </main>
        <aside className="panel" aria-label="Анализ поля">
          {error && <div className="card" role="alert">⚠ {error}</div>}
          <h3>Выбранное поле: {fieldId || "—"}</h3>
          {loading && <div className="skeleton" aria-label="Анализ выполняется">Сбор данных → ряд → ML → аномалии…</div>}
          {!!kpi.current_ndvi && (
            <>
              <div className="kpi">
                <div>NDVI<b>{kpi.current_ndvi}</b></div>
                <div>Отклонение<b>{kpi.season_deviation_pct}%</b></div>
                <div>Риск<b style={{ color: LEVEL_COLOR[kpi.level] || undefined }}>{kpi.level}</b></div>
                <div>Качество<b>{kpi.data_quality}</b></div>
              </div>
              <div ref={chartRef} style={{ height: 280 }} role="img" aria-label="Временной ряд NDVI" />
              {analysis?.anomalies?.slice(0, 3).map((a: any, i: number) => (
                <div key={i} className="card">
                  <span className={`badge ${a.level}`}>{a.level}</span> {a.start_date} — {a.end_date}
                  <div>score {a.anomaly_score} · z {a.zscore} · {a.deviation_pct}%</div>
                </div>
              ))}
              {!analysis?.anomalies?.length && <p style={{ color: "var(--text-muted)" }}>Аномалий не выявлено — поле в норме.</p>}
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
          {!!compareData.length && (
            <div className="card">
              <h4>Сравнение полей</h4>
              <div ref={compareRef} style={{ height: 240 }} role="img" aria-label="Сравнение полей" />
              {compareData.map((c: any) => (
                <div key={c.id}><b>{c.id}</b> NDVI {c.kpi?.current_ndvi} · {c.kpi?.level} · {c.kpi?.season_deviation_pct}%</div>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
