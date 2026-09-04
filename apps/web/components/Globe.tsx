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

export default function Globe({ fields, selectedId, onSelect, onAnalyze, regionCenter, flyToTrigger }: Props) {
  const globeRef = useRef<any>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);
  const [hoveredField, setHoveredField] = useState<string | null>(null);
  const [popupField, setPopupField] = useState<Field | null>(null);
  const [, setRenderTick] = useState(0); // принудительный re-render при вращении

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

  // HTML-элементы (пины)
  const pinData = fields
    .filter((f) => f.center)
    .map((f) => ({
      id: f.id,
      lat: f.center[0],
      lng: f.center[1],
      crop: f.crop,
      area_ha: f.area_ha,
      isSelected: f.id === selectedId,
      isHovered: f.id === hoveredField,
    }));

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
        // Полигоны
        polygonsData={polygonData}
        polygonGeoJsonGeometry="geoJsonGeometry"
        polygonCapColor={polyCapColor}
        polygonSideColor={polySideColor}
        polygonStrokeColor={(d: any) => d.id === selectedId ? "#ffffffaa" : "transparent"}
        polygonAltitude={(d: any) => d.id === selectedId ? 0.002 : 0.0005}
        polygonStrokeWidth={(d: any) => d.id === selectedId ? 1 : 0}
        onPolygonClick={(d: any) => onSelect(d.id)}
        // HTML-пины
        htmlElementsData={pinData}
        htmlLat="lat"
        htmlLng="lng"
        htmlAltitude={0.005}
        htmlElement={(d: any) => {
          const el = document.createElement("div");
          el.className = "globe-pin";
          el.innerHTML = `
            <div class="globe-pin-marker ${d.isSelected ? "selected" : ""} ${d.isHovered ? "hovered" : ""}">
              <svg width="24" height="34" viewBox="0 0 24 34" fill="none">
                <path d="M12 0C5.4 0 0 5.4 0 12c0 9 12 22 12 22s12-13 12-22C24 5.4 18.6 0 12 0z" fill="${d.isSelected ? "#ffffff" : "#4caf50"}"/>
                <circle cx="12" cy="11" r="5" fill="${d.isSelected ? "#4caf50" : "#000000"}" opacity="0.9"/>
              </svg>
            </div>
            ${d.isSelected ? `
              <div class="globe-popup">
                <div class="globe-popup-id">${d.id}</div>
                <div class="globe-popup-crop">${getCropRu(d.crop)}</div>
                <div class="globe-popup-area">${d.area_ha} га</div>
                <button class="globe-popup-btn" data-action="analyze" data-id="${d.id}">Анализ поля</button>
              </div>
            ` : ""}
          `;
          // Обработчики
          el.querySelector(".globe-pin-marker")?.addEventListener("click", (e) => {
            e.stopPropagation();
            onSelect(d.id);
          });
          el.querySelector("[data-action='analyze']")?.addEventListener("click", (e) => {
            e.stopPropagation();
            onAnalyze(d.id);
          });
          return el;
        }}
        // Контролы
        controlGlobe={false}
        animateIn={true}
        onGlobeRotate={() => setRenderTick((t) => t + 1)}
        onGlobeZoom={() => setRenderTick((t) => t + 1)}
        width={undefined}
        height={undefined}
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
