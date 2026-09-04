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
  regionCenter?: [number, number];
  flyToTrigger?: number;
};

const LEVEL_COLOR: Record<string, string> = {
  critical: "#e05c5c",
  stress: "#e0a83c",
  watch: "#6aa9c4",
  normal: "#7cc46a",
};

// Русские названия культур
const CROP_RU: Record<string, string> = {
  "winter wheat": "озимая пшеница",
  "пшеница": "озимая пшеница",
  "sunflower": "подсолнечник",
  "подсолнечник": "подсолнечник",
  "grain": "зерновые",
  "зерновые": "зерновые",
  "pasture": "пастбища",
  "пастбища": "пастбища",
  "corn": "кукуруза",
  "кукуруза": "кукуруза",
  "soybean": "соя",
  "соя": "соя",
};

function getCropRu(crop: string): string {
  if (!crop) return "—";
  const lower = crop.toLowerCase();
  return CROP_RU[lower] || crop;
}

export { getCropRu };

export default function Globe({ fields, selectedId, onSelect, regionCenter, flyToTrigger }: Props) {
  const globeRef = useRef<any>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);

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
    return `${c}33`;
  }, []);

  const polySideColor = useCallback((d: any) => {
    const c = LEVEL_COLOR[d.level] || LEVEL_COLOR.normal;
    return `${c}55`;
  }, []);

  // Точки — маленькие, точные
  const pointData = fields
    .filter((f) => f.center)
    .map((f) => ({
      id: f.id,
      lat: f.center[0],
      lng: f.center[1],
      isSelected: f.id === selectedId,
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
        // Маленькие точки
        pointsData={pointData}
        pointLat="lat"
        pointLng="lng"
        pointColor={(d: any) => d.isSelected ? "#ffffff" : "#4caf50"}
        pointAltitude={(d: any) => d.isSelected ? 0.003 : 0.001}
        pointRadius={(d: any) => d.isSelected ? 0.02 : 0.012}
        pointsMerge={false}
        onPointClick={(d: any) => onSelect(d.id)}
        // Контролы
        controlGlobe={false}
        animateIn={true}
        width={undefined}
        height={undefined}
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
