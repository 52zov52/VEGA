"use client";
import { useEffect, useRef, useCallback, useState } from "react";

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

const LEVEL_COLOR: Record<string, string> = {
  critical: "#f44336",
  stress: "#ff9800",
  watch: "#29b6f6",
  normal: "#4caf50",
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

type PopupPos = { x: number; y: number; field: Field };

export default function Globe({ fields, selectedId, onSelect, onAnalyze, regionCenter, flyToTrigger }: Props) {
  const globeRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);
  const [popup, setPopup] = useState<PopupPos | null>(null);

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

  // Полигоны
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
    const c = LEVEL_COLOR[d.level] || LEVEL_COLOR.normal;
    return `${c}22`;
  }, []);

  const polySideColor = useCallback((d: any) => {
    const c = LEVEL_COLOR[d.level] || LEVEL_COLOR.normal;
    return `${c}44`;
  }, []);

  // WebGL-точки (идеальная синхронизация)
  const pointData = fields
    .filter((f) => f.center)
    .map((f) => ({
      id: f.id,
      lat: f.center[0],
      lng: f.center[1],
      crop: f.crop,
      area_ha: f.area_ha,
      isSelected: f.id === selectedId,
    }));

  // Клик по WebGL-точке → показать HTML-попап
  function handlePointClick(d: any) {
    onSelect(d.id);
    // Получаем экранные координаты
    if (globeRef.current) {
      const coords = globeRef.current.getScreenCoords(d.lat, d.lng);
      if (coords) {
        const field = fields.find((f) => f.id === d.id);
        if (field) {
          setPopup({ x: coords.x, y: coords.y, field });
        }
      }
    }
  }

  // Закрыть попап при клике на пустое место
  useEffect(() => {
    function closePopup() { setPopup(null); }
    const container = containerRef.current;
    if (!container) return;
    container.addEventListener("click", closePopup);
    return () => container.removeEventListener("click", closePopup);
  }, []);

  // Летим к полю
  useEffect(() => {
    if (!globeRef.current || !selectedId) return;
    const field = fields.find((f) => f.id === selectedId);
    if (!field) return;
    const [lat, lng] = field.center;
    globeRef.current.pointOfView({ lat, lng, altitude: 0.04 }, 1600);
  }, [selectedId, flyToTrigger, fields]);

  // Летим к региону
  useEffect(() => {
    if (!globeRef.current || !regionCenter) return;
    if (selectedId) return;
    const [lat, lng] = regionCenter;
    globeRef.current.pointOfView({ lat, lng, altitude: 0.9 }, 1000);
  }, [regionCenter]);

  // Обновлять позицию попапа при вращении
  useEffect(() => {
    if (!popup || !globeRef.current) return;
    function updatePos() {
      if (!popup || !globeRef.current || !globeRef.current.getScreenCoords) return;
      const coords = globeRef.current.getScreenCoords(popup.field.center[0], popup.field.center[1]);
      if (coords) {
        setPopup((prev) => prev ? { ...prev, x: coords.x, y: coords.y } : null);
      }
    }
    const globe = globeRef.current;
    globe?.addEventListener?.("globe-rotate", updatePos);
    // Also poll during animation
    const iv = setInterval(updatePos, 50);
    setTimeout(() => clearInterval(iv), 2000);
    return () => {
      globe?.removeEventListener?.("globe-rotate", updatePos);
      clearInterval(iv);
    };
  }, [popup?.field?.id]);

  if (!ready || !GlobeComp) {
    return (
      <div className="globe-loading">
        <div className="globe-loading-spinner" />
        <span>Загрузка глобуса…</span>
      </div>
    );
  }

  return (
    <div className="globe-container" ref={containerRef}>
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
        // Полигоны
        polygonsData={polygonData}
        polygonGeoJsonGeometry="geoJsonGeometry"
        polygonCapColor={polyCapColor}
        polygonSideColor={polySideColor}
        polygonStrokeColor={(d: any) => d.id === selectedId ? "#ffffffaa" : "transparent"}
        polygonAltitude={(d: any) => d.id === selectedId ? 0.002 : 0.0005}
        polygonStrokeWidth={(d: any) => d.id === selectedId ? 1 : 0}
        onPolygonClick={(d: any) => onSelect(d.id)}
        // WebGL-точки
        pointsData={pointData}
        pointLat="lat"
        pointLng="lng"
        pointColor={(d: any) => d.isSelected ? "#ffffff" : "#4caf50"}
        pointAltitude={0.001}
        pointRadius={(d: any) => d.isSelected ? 0.15 : 0.08}
        onPointClick={(d: any) => handlePointClick(d)}
        // Контролы
        controlGlobe={false}
        animateIn={true}
        width={undefined}
        height={undefined}
        style={{ width: "100%", height: "100%" }}
      />

      {/* HTML-попап поверх глобуса */}
      {popup && (
        <div
          className="globe-popup-overlay"
          style={{ left: popup.x, top: popup.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="globe-popup">
            <div className="globe-popup-id">{popup.field.id}</div>
            <div className="globe-popup-crop">{getCropRu(popup.field.crop)}</div>
            <div className="globe-popup-area">{popup.field.area_ha} га</div>
            <button
              className="globe-popup-btn"
              onClick={(e) => { e.stopPropagation(); onAnalyze(popup.field.id); setPopup(null); }}
            >
              Анализ поля
            </button>
          </div>
          <div className="globe-popup-arrow" />
        </div>
      )}
    </div>
  );
}
