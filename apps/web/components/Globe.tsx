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
  onFieldHover?: (id: string | null) => void;
  regionCenter?: [number, number];
  flyToTrigger?: number;
};

const LEVEL_COLOR: Record<string, string> = {
  critical: "#e05c5c",
  stress: "#e0a83c",
  watch: "#6aa9c4",
  normal: "#7cc46a",
};

export default function Globe({ fields, selectedId, onSelect, onFieldHover, regionCenter, flyToTrigger }: Props) {
  const globeRef = useRef<any>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);
  const prevSelected = useRef<string>("");

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

  // Полигоны полей
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
    return `${c}44`;
  }, []);

  const polySideColor = useCallback((d: any) => {
    const c = LEVEL_COLOR[d.level] || LEVEL_COLOR.normal;
    return `${c}77`;
  }, []);

  // Точки (маркеры) — одно выбранное поле
  const pointData = fields
    .filter((f) => f.id === selectedId && f.center)
    .map((f) => ({
      id: f.id,
      lat: f.center[0],
      lng: f.center[1],
      size: 0.6,
      color: "#7cc46a",
      label: f.id,
    }));

  // Летим к полю при выборе
  useEffect(() => {
    if (!globeRef.current || !selectedId) return;
    const field = fields.find((f) => f.id === selectedId);
    if (!field) return;
    const [lat, lng] = field.center;
    globeRef.current.pointOfView({ lat, lng, altitude: 0.5 }, 1200);
  }, [selectedId, flyToTrigger, fields]);

  // Летим к региону
  useEffect(() => {
    if (!globeRef.current || !regionCenter) return;
    if (selectedId) return; // если поле выбрано — летим к полю
    const [lat, lng] = regionCenter;
    globeRef.current.pointOfView({ lat, lng, altitude: 0.8 }, 1000);
  }, [regionCenter]);

  if (!ready || !GlobeComp) {
    return (
      <div style={{
        width: "100%", height: "100%", display: "flex",
        alignItems: "center", justifyContent: "center",
        background: "#0a0e09", color: "var(--text-muted)",
        fontSize: 13,
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
      atmosphereAltitude={0.15}
      globeTileEngineUrl={(x: number, y: number, l: number) =>
        `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${l}/${y}/${x}`
      }
      // Полигоны
      polygonsData={polygonData}
      polygonGeoJsonGeometry="geoJsonGeometry"
      polygonCapColor={polyCapColor}
      polygonSideColor={polySideColor}
      polygonStrokeColor={(d: any) => d.id === selectedId ? "#ffffffcc" : "transparent"}
      polygonAltitude={(d: any) => d.id === selectedId ? 0.006 : 0.002}
      onPolygonClick={(d: any) => onSelect(d.id)}
      polygonStrokeWidth={(d: any) => d.id === selectedId ? 2 : 0}
      // Точки (маркеры)
      pointsData={pointData}
      pointLat="lat"
      pointLng="lng"
      pointColor="color"
      pointAltitude={0.01}
      pointRadius={0.35}
      pointsMerge={false}
      onPointClick={(d: any) => onSelect(d.id)}
      // Labels
      labelsData={pointData}
      labelLat="lat"
      labelLng="lng"
      labelText="label"
      labelSize={0.8}
      labelDotRadius={0.3}
      labelColor={() => "#7cc46a"}
      labelResolution={2}
      labelAltitude={0.012}
      // Controls
      controlGlobe={false}
      animateIn={true}
      width={undefined}
      height={undefined}
      style={{ width: "100%", height: "100%" }}
    />
  );
}
