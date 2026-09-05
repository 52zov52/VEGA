"use client";
import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import Modal from "../components/Modal";
import { LoadingSkeleton, EmptyState, ErrorState, PipelineState } from "../components/UIStates";
import { fetchAnalysis } from "../lib/api";

const Globe = dynamic(() => import("../components/Globe"), { ssr: false });
import { getCropRu } from "../components/Globe";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Field = { id: string; region_id: string; crop: string; area_ha: number; center: [number, number]; geometry?: any };
type SavedPoly = { id: string; name: string; geometry: any; area_ha?: number; center?: [number, number] };

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

// Живая площадь рисуемого контура (та же формула, что на бэке)
function polyAreaHa(vertices: [number, number][]): number {
  if (vertices.length < 3) return 0;
  let s = 0;
  for (let i = 0; i < vertices.length; i++) {
    const [x1, y1] = vertices[i];
    const [x2, y2] = vertices[(i + 1) % vertices.length];
    s += x1 * y2 - x2 * y1;
  }
  const avgLat = vertices.reduce((a, p) => a + p[1], 0) / vertices.length * Math.PI / 180;
  return Math.abs(s) / 2 * 111.32 * 111.32 * Math.max(Math.cos(avgLat), 0.2) * 100;
}

// Свой полигон -> то же поле для карты: центр и площадь считаем по bbox геометрии
function fieldFromSaved(p: SavedPoly): Field {
  const ring: [number, number][] = p.geometry?.coordinates?.[0] || [];
  if (!ring.length) {
    return { id: p.id, region_id: "", crop: "unknown", area_ha: p.area_ha || 0, center: p.center || [47.2, 39.7], geometry: p.geometry };
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
    area_ha: p.area_ha ?? Math.round(areaHa * 10) / 10,
    center: p.center || [(minLat + maxLat) / 2, (minLng + maxLng) / 2],
    geometry: p.geometry,
  };
}

export default function Page() {
  const router = useRouter();
  const [regions, setRegions] = useState<any[]>([]);
  const [regionQuery, setRegionQuery] = useState("");
  const [regionId, setRegionId] = useState("rostov");
  const [fields, setFields] = useState<Field[]>([]);
  const [fieldsState, setFieldsState] = useState<"idle" | "loading" | "empty" | "error">("idle");
  const [fieldsSource, setFieldsSource] = useState<string>("");
  const [fieldId, setFieldId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState({ agriculture: true, ndvi: true, anomaly: true });
  const [drawMode, setDrawMode] = useState(false);
  const [vertices, setVertices] = useState<[number, number][]>([]);
  const [drawName, setDrawName] = useState("");
  const [saved, setSaved] = useState<SavedPoly[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  // Новый регион в любой точке планеты (критерий адаптивности)
  const [showAddRegion, setShowAddRegion] = useState(false);
  const [newRegionName, setNewRegionName] = useState("");
  const [newRegionLat, setNewRegionLat] = useState("");
  const [newRegionLon, setNewRegionLon] = useState("");
  const searchTimer = useRef<any>(null);

  function onRegionQuery(v: string) {
    setRegionQuery(v);
    // дебаунс: живой геокодер не дёргаем на каждую букву
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => loadRegions(v), 400);
  }

  async function pickRegion(id: string) {
    // кандидат геокодера (osm-...) — сначала регистрируем как регион
    if (id.startsWith("osm-")) {
      const cand = regions.find((r: any) => r.id === id);
      if (!cand?.center) { setRegionId(id); return; }
      try {
        const r = await fetch(`${API}/api/regions`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: cand.name || id, center: cand.center }),
        });
        const reg = await r.json();
        if (!r.ok) { setError(`Регион не создан: ${reg.detail || `ошибка ${r.status}`}.`); return; }
        await loadRegions(regionQuery);
        setRegionId(reg.id);
      } catch { setError("Не удалось создать регион."); }
      return;
    }
    setRegionId(id);
  }
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareData, setCompareData] = useState<any[]>([]);
  const [comparing, setComparing] = useState(false);
  const [globeFlyTo, setGlobeFlyTo] = useState(0);
  const [compareOpen, setCompareOpen] = useState(false);
  // Dive-переход на страницу анализа: id поля + счётчик для триггера зума камеры
  const [diving, setDiving] = useState<string | null>(null);
  const [diveKey, setDiveKey] = useState(0);
  // Мобильная панель: drawer с контролами поверх карты
  const [sidebarOpen, setSidebarOpen] = useState(false);

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
    setFieldsSource("");
    fetch(`${API}/api/regions/${regionId}/fields?limit=60`).then((r) => r.json())
      .then((j) => {
        const list = j.fields || [];
        setFields(list);
        setFieldsSource(j.source || "");
        setFieldsState(list.length ? "idle" : "empty");
        if (list.length && !fieldId) setFieldId(list[0].id);
      })
      .catch(() => setFieldsState("error"));
  }, [regionId]);

  const savedFields = useMemo<Field[]>(() => saved.map(fieldFromSaved), [saved]);
  const globeFields = useMemo(() => [...fields, ...savedFields], [fields, savedFields]);
  // Центр региона — из API (включая кастомные), хардкод лишь запасной
  const regionCenter = useMemo<[number, number]>(() => {
    const found = regions.find((r: any) => r.id === regionId);
    if (found?.center && found.center.length === 2) return [Number(found.center[0]), Number(found.center[1])];
    return REGION_COORDS[regionId] || [47.2, 39.7];
  }, [regions, regionId]);

  async function addRegion() {
    const lat = Number(String(newRegionLat).replace(",", "."));
    const lon = Number(String(newRegionLon).replace(",", "."));
    if (!newRegionName.trim() || !isFinite(lat) || !isFinite(lon)) {
      setError("Для региона нужны название и числа lat/lon."); return;
    }
    try {
      const r = await fetch(`${API}/api/regions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newRegionName.trim(), center: [lat, lon] }),
      });
      const reg = await r.json();
      if (!r.ok) { setError(`Регион не создан: ${reg.detail || `ошибка ${r.status}`}.`); return; }
      setNewRegionName(""); setNewRegionLat(""); setNewRegionLon(""); setShowAddRegion(false);
      await loadRegions(regionQuery);
      setRegionId(reg.id);
    } catch { setError("Не удалось создать регион."); }
  }

  async function deleteRegion() {
    if (!regionId.startsWith("custom-")) return;
    try {
      const r = await fetch(`${API}/api/regions/${regionId}`, { method: "DELETE" });
      if (!r.ok) { setError("Не удалось удалить регион."); return; }
      setRegionId("rostov");
      await loadRegions(regionQuery);
    } catch { setError("Не удалось удалить регион."); }
  }

  const handleFieldSelect = useCallback((id: string) => {
    if (diving) return;
    setFieldId(id);
    setGlobeFlyTo((n) => n + 1);
    // На мобилке после выбора закрываем drawer, чтобы было видно карту
    setSidebarOpen(false);
  }, [diving]);

  // Ресайз до десктопа — сбрасываем мобильный drawer
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth > 1024) setSidebarOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Esc закрывает мобильную панель
  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSidebarOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sidebarOpen]);

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
        body: JSON.stringify({ region_id: regionId, name: drawName.trim() || undefined, geometry }),
      });
      const poly = await r.json();
      if (!r.ok) { setError(`Не удалось сохранить: ${poly.detail || `ошибка ${r.status}`}.`); return; }
      setSaved((s) => [...s, poly]);
      const field = fieldFromSaved(poly);
      setFieldId(field.id);
      setGlobeFlyTo((n) => n + 1);
      setVertices([]); setDrawMode(false); setDrawName("");
    } catch { setError("Не удалось сохранить полигон."); }
  }

  async function renameSaved(id: string) {
    const name = editName.trim();
    if (!name) { setEditingId(null); return; }
    try {
      const r = await fetch(`${API}/api/polygons/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const poly = await r.json();
      if (!r.ok) { setError(`Не удалось переименовать: ${poly.detail || `ошибка ${r.status}`}.`); return; }
      setSaved((s) => s.map((p) => (p.id === id ? poly : p)));
      setEditingId(null);
    } catch { setError("Не удалось переименовать полигон."); }
  }

  async function deleteSaved(id: string) {
    try {
      await fetch(`${API}/api/polygons/${id}`, { method: "DELETE" });
      setSaved((s) => s.filter((p) => p.id !== id));
    } catch { setError("Не удалось удалить полигон."); }
  }

  // Анализ из попапа на глобусе: кинематографичный dive —
  // камера пикирует в точку поля, экран заливается чёрным,
  // и уже под чёрным экраном открывается страница расширенного анализа.
  async function handleAnalyzeField(pid: string) {
    if (diving) return;
    setFieldId(pid);
    setGlobeFlyTo((n) => n + 1);
    setDiving(pid);
    setDiveKey((n) => n + 1);
    setTimeout(() => {
      router.push(`/field/${encodeURIComponent(pid)}?region=${regionId}`);
    }, 1600);
  }

  async function runCompare() {
    if (compareIds.length < 2) { setError("Для сравнения выберите 2–5 полей."); return; }
    setComparing(true); setError(null);
    try {
      const rows = [];
      for (const pid of compareIds.slice(0, 5)) {
        const f = globeFields.find((x) => x.id === pid);
        const opts = f?.center ? { lat: f.center[0], lon: f.center[1] } : {};
        rows.push({ id: pid, ...(await fetchAnalysis(pid, regionId, opts)) });
      }
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

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <button
            className="header-burger"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={sidebarOpen ? "Скрыть панели" : "Показать панели"}
            aria-expanded={sidebarOpen}
          >
            {sidebarOpen ? "✕" : "☰"}
          </button>
          <span className="header-logo">◇</span>
          <span className="header-title">VEGA</span>
          <span className="header-sub">Мониторинг вегетации</span>
        </div>
        <div className="header-actions">
          {fieldId && (
            <button className="btn-secondary btn-sm header-analyze" onClick={() => handleAnalyzeField(fieldId)}>
              Анализ →
            </button>
          )}
        </div>
      </header>

      {/* Layout: sidebar + globe (без правой панели) */}
      <div className="layout layout--no-panel">
        {/* Затемнение под мобильным drawer */}
        {sidebarOpen && (
          <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
        )}
        {/* Sidebar */}
        <aside className={`sidebar${sidebarOpen ? " open" : ""}`}>
          <div className="sidebar-mobile-head">
            <span className="sidebar-mobile-title">Панели управления</span>
            <button className="modal-close" onClick={() => setSidebarOpen(false)} aria-label="Закрыть панели">✕</button>
          </div>
          <div className="sidebar-section">
            <label className="label" htmlFor="region-search">Регион</label>
            <input
              id="region-search"
              className="input"
              placeholder="Поиск региона…"
              value={regionQuery}
              onChange={(e) => onRegionQuery(e.target.value)}
            />
            <select
              className="input select"
              value={regionId}
              onChange={(e) => pickRegion(e.target.value)}
            >
              {(regions.length ? regions : [
                { id: "rostov", name: "Ростовская область" },
                { id: "krasnodar", name: "Краснодарский край" },
                { id: "voronezh", name: "Воронежская область" },
                { id: "stavropol", name: "Ставропольский край" },
                { id: "belgorod", name: "Белгородская область" },
                { id: "tatarstan", name: "Республика Татарстан" },
              ]).map((r: any) => (
                <option key={r.id} value={r.id}>{r.name}{r.source === "nominatim" ? " 🌍" : ""}</option>
              ))}
            </select>
            <div className="draw-actions">
              <button className="btn-ghost btn-sm" onClick={() => setShowAddRegion((v) => !v)}>
                {showAddRegion ? "Скрыть" : "＋ регион"}
              </button>
              {regionId.startsWith("custom-") && (
                <button className="btn-ghost btn-sm" onClick={deleteRegion}>Удалить регион</button>
              )}
            </div>
            {showAddRegion && (
              <div className="draw-info">
                <span>Новая территория: название + центр. Контуры найдутся сами.</span>
                <input className="input" placeholder="Название…" value={newRegionName} maxLength={80} onChange={(e) => setNewRegionName(e.target.value)} />
                <div className="draw-actions">
                  <input className="input" placeholder="lat" value={newRegionLat} inputMode="decimal" onChange={(e) => setNewRegionLat(e.target.value)} />
                  <input className="input" placeholder="lon" value={newRegionLon} inputMode="decimal" onChange={(e) => setNewRegionLon(e.target.value)} />
                </div>
                <button className="btn-primary btn-sm btn-full" onClick={addRegion}>Добавить</button>
              </div>
            )}
          </div>

          <div className="sidebar-section">
            <div className="sidebar-section-header">
              <span className="label">Поля</span>
              <span className="badge-count">{fields.length}</span>
            </div>
            {fieldsSource && (
              <span className="source-badge" title={fieldsSource.startsWith("overpass") ? "Контуры farmland из OpenStreetMap, найденные автоматически" : "Демо-сетка: реальные контуры недоступны"}>
                {fieldsSource.startsWith("overpass") ? "◉ OSM-контуры" : "◇ демо-сетка"}
              </span>
            )}
            {fieldsState === "loading" && <LoadingSkeleton text="Ищем контуры OSM (первый раз до ~30 сек)…" />}
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
              ? <button className="btn-secondary btn-full" onClick={() => { setDrawMode(true); setVertices([]); setDrawName(""); setSidebarOpen(false); }}>✏ Нарисовать</button>
              : (
                <div className="draw-info">
                  <span>Точек: {vertices.length}. Нужно ≥ 3.{vertices.length >= 3 && ` ≈${Math.round(polyAreaHa(vertices)).toLocaleString("ru-RU")} га`}</span>
                  <input
                    className="input"
                    placeholder="Название участка…"
                    value={drawName}
                    maxLength={80}
                    onChange={(e) => setDrawName(e.target.value)}
                  />
                  <div className="draw-actions">
                    <button className="btn-primary btn-sm" onClick={finishDrawing} disabled={vertices.length < 3}>Готово</button>
                    <button className="btn-secondary btn-sm" onClick={() => setVertices((v) => v.slice(0, -1))} disabled={!vertices.length}>↩ Точка</button>
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
                  <div className="field-card-header">
                    <span className="field-card-id">{p.id}</span>
                    {p.area_ha != null && <span className="field-card-area">{Math.round(p.area_ha).toLocaleString("ru-RU")} га</span>}
                  </div>
                  {editingId === p.id ? (
                    <div className="draw-actions">
                      <input
                        className="input"
                        value={editName}
                        maxLength={80}
                        autoFocus
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") renameSaved(p.id); if (e.key === "Escape") setEditingId(null); }}
                      />
                      <button className="btn-primary btn-sm" onClick={() => renameSaved(p.id)}>ОК</button>
                    </div>
                  ) : (
                    <span
                      className="saved-name"
                      title="Нажмите, чтобы переименовать"
                      onClick={() => { setEditingId(p.id); setEditName(p.name || ""); }}
                    >{p.name || p.id} ✎</span>
                  )}
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
        <main className={(drawMode ? "globe-wrap drawing" : "globe-wrap") + (diving ? " diving" : "")}>
          <Globe
            fields={globeFields}
            selectedId={fieldId}
            onSelect={handleFieldSelect}
            onAnalyze={handleAnalyzeField}
            regionCenter={regionCenter}
            flyToTrigger={globeFlyTo}
            drawMode={drawMode}
            onDrawPoint={handleDrawPoint}
            layers={layers}
            diveId={diving}
            diveKey={diveKey}
          />
          {/* Мобильные быстрые действия поверх карты */}
          <div className="globe-fab-stack" aria-hidden={sidebarOpen ? true : undefined}>
            <button
              className={`globe-fab${sidebarOpen ? " active" : ""}`}
              onClick={() => setSidebarOpen((v) => !v)}
              aria-label="Панели управления"
            >
              ☰
            </button>
            <button
              className={`globe-fab${drawMode ? " active" : ""}`}
              onClick={() => {
                if (drawMode) { setDrawMode(false); setVertices([]); }
                else { setDrawMode(true); setVertices([]); setDrawName(""); setSidebarOpen(false); }
              }}
              aria-label={drawMode ? "Отменить рисование" : "Нарисовать полигон"}
              title={drawMode ? "Отменить рисование" : "Нарисовать полигон"}
            >
              {drawMode ? "✕" : "✏"}
            </button>
          </div>
          {drawMode && (
            <div className="draw-overlay">
              ✏ Тапните {Math.max(0, 3 - vertices.length)}+ точек на карте
              {vertices.length > 0 && ` · уже ${vertices.length}`}
              <span className="draw-overlay-actions">
                <button className="btn-primary btn-sm" onClick={finishDrawing} disabled={vertices.length < 3}>Готово</button>
                <button className="btn-secondary btn-sm" onClick={() => { setDrawMode(false); setVertices([]); }}>Отмена</button>
              </span>
            </div>
          )}
          {/* Мобильная нижняя карточка выбранного поля — попап на глобусе мелкий для пальца */}
          {fieldId && !drawMode && !diving && (() => {
            const f = globeFields.find((x) => x.id === fieldId);
            if (!f) return null;
            return (
              <div className="mobile-selected-bar">
                <div className="mobile-selected-info" onClick={() => handleAnalyzeField(fieldId)}>
                  <span className="mobile-selected-id">{f.id}</span>
                  <span className="mobile-selected-meta">{getCropRu(f.crop)} · {f.area_ha} га</span>
                </div>
                <button className="btn-primary mobile-selected-btn" onClick={() => handleAnalyzeField(fieldId)}>
                  Анализ →
                </button>
              </div>
            );
          })()}
          {diving && (
            <div className="dive-overlay visible">
              <div className="dive-spinner" />
              <div className="dive-text">Анализ поля {diving}…</div>
            </div>
          )}
        </main>
      </div>

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
