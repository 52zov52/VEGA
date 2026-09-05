"use client";
import { useEffect, useRef, useState, useCallback } from "react";

type Field = {
  id: string;
  region_id: string;
  crop: string;
  area_ha: number;
  center: [number, number];
  geometry?: any;
  level?: string;
};

type Props = {
  fields: Field[];
  selectedId: string;
  onSelect: (id: string) => void;
  onAnalyze: (id: string) => void;
  regionCenter?: [number, number];
  flyToTrigger?: number;
};

const CROP_RU: Record<string, string> = {
  "winter wheat": "Озимая пшеница",
  "пшеница": "Озимая пшеница",
  "sunflower": "Подсолнечник",
  "подсолнечник": "Подсолнечник",
  "grain": "Зерновые",
  "зерновые": "Зерновые",
  "pasture": "Пастбища",
  "пастбища": "Пастбища",
  "corn": "Кукуруза",
  "кукуруза": "Кукуруза",
  "soybean": "Соя",
  "соя": "Соя",
};

function getCropRu(crop: string): string {
  if (!crop) return "—";
  return CROP_RU[crop.toLowerCase()] || crop;
}

export { getCropRu };

// HTML-маркеры в стиле Google Maps: один rAF-цикл двигает все div'ы
// через getScreenCoords каждый кадр — привязка жёсткая, отставания нет.
// Клики — обычные DOM onClick. Маршрут на обратной стороне глобуса прячем.
function MarkersOverlay({ globeRef, fields, selectedId, onSelect }: {
  globeRef: React.RefObject<any>;
  fields: Field[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const elsRef = useRef(new Map<string, HTMLDivElement>());

  const setEl = useCallback((id: string) => (el: HTMLDivElement | null) => {
    if (el) elsRef.current.set(id, el);
    else elsRef.current.delete(id);
  }, []);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const g = globeRef.current;
      if (g?.getScreenCoords) {
        let cam: any = null;
        let R = 100;
        try {
          const c = g.camera?.();
          if (c?.position) { cam = c.position; R = g.getGlobeRadius?.() ?? 100; }
        } catch { cam = null; }
        const dist = cam ? Math.sqrt(cam.x * cam.x + cam.y * cam.y + cam.z * cam.z) : 0;
        for (const f of fields) {
          const el = elsRef.current.get(f.id);
          if (!el || !f.center) continue;
          try {
            const p = g.getScreenCoords(f.center[0], f.center[1]);
            let vis = !!p && typeof p.x === "number";
            if (vis && cam && dist > 0) {
              const m = g.getCoords(f.center[0], f.center[1], 0);
              const cosAng = (m.x * cam.x + m.y * cam.y + m.z * cam.z) / (R * dist);
              if (cosAng <= R / dist) vis = false; // обратная сторона
            }
            if (vis) {
              el.style.transform = `translate(-50%, -100%) translate(${p.x}px, ${p.y}px)`;
              el.style.opacity = "1";
              el.style.pointerEvents = "auto";
            } else {
              el.style.opacity = "0";
              el.style.pointerEvents = "none";
            }
          } catch { /* ignore */ }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [globeRef, fields]);

  return (
    <div className="globe-markers">
      {fields.filter((f) => f.center).map((f) => {
        const sel = f.id === selectedId;
        const fill = sel ? "#ffffff" : "#4caf50";
        const dot = sel ? "#4caf50" : "#0a0a0a";
        return (
          <div
            key={f.id}
            ref={setEl(f.id)}
            className={`globe-marker${sel ? " selected" : ""}`}
            style={{ opacity: 0 }}
            title={`${f.id} · ${getCropRu(f.crop)}`}
            onClick={(e) => { e.stopPropagation(); onSelect(f.id); }}
          >
            <svg width={sel ? 32 : 26} height={sel ? 46 : 38} viewBox="0 0 28 40">
              <path
                d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.3 21.7 0 14 0z"
                fill={fill}
              />
              <circle cx="14" cy="14" r="6" fill={dot} />
            </svg>
          </div>
        );
      })}
    </div>
  );
}

// Попап, привязанный к пину: каждый кадр пересчитывает экранные
// координаты через getScreenCoords и двигает div напрямую через ref
// (без setState на каждый кадр), поэтому ходит за глобусом.
function AnchoredPopup({ globeRef, field, onAnalyze }: {
  globeRef: React.RefObject<any>;
  field: Field;
  onAnalyze: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const g = globeRef.current;
      const el = ref.current;
      if (g?.getScreenCoords && el) {
        try {
          const p = g.getScreenCoords(field.center[0], field.center[1]);
          if (p && typeof p.x === "number" && typeof p.y === "number") {
            el.style.transform = `translate(-50%, -100%) translate(${p.x}px, ${p.y}px) translateY(-18px)`;
            el.style.opacity = "1";
          } else {
            el.style.opacity = "0";
          }
        } catch { /* ignore */ }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [globeRef, field]);

  return (
    <div ref={ref} className="globe-popup-anchor" style={{ opacity: 0 }} onClick={(e) => e.stopPropagation()}>
      <div className="globe-popup">
        <div className="globe-popup-id">{field.id}</div>
        <div className="globe-popup-crop">{getCropRu(field.crop)}</div>
        <div className="globe-popup-area">{field.area_ha} га</div>
        <button
          className="globe-popup-btn"
          onClick={(e) => { e.stopPropagation(); onAnalyze(field.id); }}
        >
          Анализ поля
        </button>
      </div>
      <div className="globe-popup-arrow" />
    </div>
  );
}

export default function Globe({ fields, selectedId, onSelect, onAnalyze, regionCenter, flyToTrigger }: Props) {
  const globeRef = useRef<any>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);
  const [popup, setPopup] = useState<{ field: Field } | null>(null);

  useEffect(() => {
    let cancelled = false;
    import("react-globe.gl").then((mod) => {
      if (!cancelled) {
        setGlobeComp(() => mod.default);
        setReady(true);
      }
    });
    return () => { cancelled = true; };
  }, []);

  const polygonData = fields
    .filter((f) => f.geometry?.coordinates)
    .map((f) => ({
      id: f.id,
      level: f.level || "normal",
      geoJsonGeometry: JSON.stringify({
        type: "Polygon",
        coordinates: [f.geometry.coordinates[0]],
      }),
    }));

  const polyCapColor = useCallback((d: any) => {
    const colors: Record<string, string> = { critical: "#f44336", stress: "#ff9800", watch: "#29b6f6" };
    return `${colors[d.level] || "#4caf50"}22`;
  }, []);

  const polySideColor = useCallback((d: any) => {
    const colors: Record<string, string> = { critical: "#f44336", stress: "#ff9800", watch: "#29b6f6" };
    return `${colors[d.level] || "#4caf50"}44`;
  }, []);

  // Летим к полю
  useEffect(() => {
    if (!globeRef.current || !selectedId) return;
    const field = fields.find((f) => f.id === selectedId);
    if (!field) return;
    globeRef.current.pointOfView({ lat: field.center[0], lng: field.center[1], altitude: 0.0012 }, 1600);
  }, [selectedId, flyToTrigger, fields]);

  // Попап при любом выделении поля (сайдбар, полигон, пин).
  // Позицию каждый кадр считает сам AnchoredPopup, здесь только открываем.
  useEffect(() => {
    if (!selectedId) { setPopup(null); return; }
    const field = fields.find((f) => f.id === selectedId);
    if (field) setPopup({ field });
  }, [selectedId, flyToTrigger, fields]);

  useEffect(() => {
    if (!globeRef.current || !regionCenter) return;
    if (selectedId) return;
    globeRef.current.pointOfView({ lat: regionCenter[0], lng: regionCenter[1], altitude: 0.9 }, 1000);
  }, [regionCenter, selectedId]);

  if (!ready || !GlobeComp) {
    return (
      <div className="globe-loading">
        <div className="globe-loading-spinner" />
        <span>Загрузка глобуса…</span>
      </div>
    );
  }

  return (
    <div className="globe-container">
      <GlobeComp
        ref={globeRef}
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-blue-marble.jpg"
        backgroundImageUrl=""
        backgroundColor="rgba(0,0,0,0)"
        atmosphereColor="#4fc3f7"
        atmosphereAltitude={0.25}
        globeTileEngineUrl={(x: number, y: number, l: number) =>
          `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${l}/${y}/${x}`
        }
        polygonsData={polygonData}
        polygonGeoJsonGeometry="geoJsonGeometry"
        polygonCapColor={polyCapColor}
        polygonSideColor={polySideColor}
        polygonStrokeColor={(d: any) => d.id === selectedId ? "#ffffffaa" : "transparent"}
        polygonAltitude={(d: any) => d.id === selectedId ? 0.002 : 0.0005}
        polygonStrokeWidth={(d: any) => d.id === selectedId ? 1 : 0}
        onPolygonClick={(d: any) => onSelect(d.id)}
        onGlobeClick={() => setPopup(null)}
        controlGlobe={false}
        animateIn={true}
        width={undefined}
        height={undefined}
        style={{ width: "100%", height: "100%" }}
      />

      {/* HTML-маркеры Google Maps поверх WebGL */}
      <MarkersOverlay
        globeRef={globeRef}
        fields={fields}
        selectedId={selectedId}
        onSelect={onSelect}
      />

      {popup && (
        <AnchoredPopup
          globeRef={globeRef}
          field={popup.field}
          onAnalyze={(id) => { onAnalyze(id); setPopup(null); }}
        />
      )}
    </div>
  );
}
