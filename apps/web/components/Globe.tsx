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
  onCameraChange?: (lat: number, lng: number, altitude: number) => void;
  regionCenter?: [number, number];
  flyTo?: number;
};

const LEVEL_COLOR: Record<string, string> = {
  critical: "#e05c5c",
  stress: "#e0a83c",
  watch: "#6aa9c4",
  normal: "#7cc46a",
};

// Спутниковые тайлы ESRI World Imagery — бесплатные, 1м разрешение, без API-ключа
const ESRI_TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

export default function Globe({ fields, selectedId, onSelect, regionCenter, flyTo }: Props) {
  const globeRef = useRef<any>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);

  // Динамический импорт — отключаем SSR (react-globe.gl требует window)
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

  // Генерируем GeoJSON-полигоны для отрисовки на глобусе
  const polygonData = fields
    .filter((f) => f.geometry?.coordinates)
    .map((f) => {
      const coords = f.geometry.coordinates[0];
      // polygonGeoJsonGeometry ожидает { type: "Polygon", coordinates: [...] }
      return {
        id: f.id,
        level: f.level || "normal",
        geoJsonGeometry: JSON.stringify({
          type: "Polygon",
          coordinates: [coords],
        }),
      };
    });

  // Цвет полигона по уровню риска
  const polyCapColor = useCallback((d: any) => {
    const c = LEVEL_COLOR[d.level] || LEVEL_COLOR.normal;
    return `${c}55`; // полупрозрачный
  }, []);

  const polySideColor = useCallback((d: any) => {
    const c = LEVEL_COLOR[d.level] || LEVEL_COLOR.normal;
    return `${c}88`;
  }, []);

  // Летать к региону при смене
  useEffect(() => {
    if (!globeRef.current || !regionCenter) return;
    const [lat, lng] = regionCenter;
    globeRef.current.pointOfView({ lat, lng, altitude: 0.8 }, 1000);
  }, [regionCenter, flyTo]);

  if (!ready || !GlobeComp) {
    return (
      <div style={{
        width: "100%", height: "100%", display: "flex",
        alignItems: "center", justifyContent: "center",
        background: "#0a0e09", color: "var(--text-muted)",
      }}>
        Загрузка глобуса…
      </div>
    );
  }

  return (
    <GlobeComp
      ref={globeRef}
      globeImageUrl="//unpkg.com/three-globe/example/img/earth-blue-marble.jpg"
      backgroundImageUrl=""
      backgroundColor="#0a0e09"
      atmosphereColor="#7cc46a"
      atmosphereAltitude={0.2}
      // Спутниковые тайлы поверх текстуры Земли
      globeTileEngineUrl={(x: number, y: number, l: number) =>
        `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${l}/${y}/${x}`
      }
      // Полигоны полей
      polygonsData={polygonData}
      polygonGeoJsonGeometry="geoJsonGeometry"
      polygonCapColor={polyCapColor}
      polygonSideColor={polySideColor}
      polygonStrokeColor={(d: any) => d.id === selectedId ? "#ffffff" : "transparent"}
      polygonAltitude={(d: any) => d.id === selectedId ? 0.008 : 0.003}
      onPolygonClick={(d: any) => onSelect(d.id)}
      // Клик по глобусу — выбор точки
      onGlobeClick={(d: any) => {
        // клик по пустому месту — ничего
      }}
      // Кастомные HTML-маркеры для избранных полей
      labelsData={fields.filter((f) => f.id === selectedId)}
      labelLat="lat"
      labelLng="lng"
      labelText={() => ""}
      labelSize={0}
      // Контролы
      controlGlobe={false}
      animateIn={true}
      width={undefined}
      height={undefined}
      style={{ width: "100%", height: "100%" }}
    />
  );
}
