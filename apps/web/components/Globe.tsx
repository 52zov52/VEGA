"use client";
import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import * as THREE from "three";

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

// Большой 3D-пин (для отдаления): палочка + сфера
function createBigPin(isSelected: boolean): THREE.Group {
  const group = new THREE.Group();
  const color = isSelected ? 0xffffff : 0x4caf50;

  const stickGeo = new THREE.CylinderGeometry(0.008, 0.008, 0.08, 8);
  const stickMat = new THREE.MeshBasicMaterial({ color });
  const stick = new THREE.Mesh(stickGeo, stickMat);
  stick.rotation.x = Math.PI / 2;
  stick.position.z = 0.04;
  group.add(stick);

  const headGeo = new THREE.SphereGeometry(0.02, 16, 16);
  const headMat = new THREE.MeshBasicMaterial({ color: isSelected ? 0x4caf50 : 0x1a1a1a });
  const head = new THREE.Mesh(headGeo, headMat);
  head.position.z = 0.085;
  group.add(head);

  return group;
}

// Маленькая точка (для приближения)
function createSmallDot(isSelected: boolean): THREE.Group {
  const group = new THREE.Group();
  const color = isSelected ? 0xffffff : 0x4caf50;
  const geo = new THREE.SphereGeometry(0.008, 8, 8);
  const mat = new THREE.MeshBasicMaterial({ color });
  const mesh = new THREE.Mesh(geo, mat);
  group.add(mesh);
  return group;
}

const LOD_THRESHOLD = 0.15;

export default function Globe({ fields, selectedId, onSelect, onAnalyze, regionCenter, flyToTrigger }: Props) {
  const globeRef = useRef<any>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);
  const [popup, setPopup] = useState<{ field: Field; x: number; y: number } | null>(null);
  const zoomRef = useRef(0.9);
  const [lodKey, setLodKey] = useState<"far" | "near">("far");

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
    const colors: Record<string, string> = { critical: "#f44336", stress: "#ff9800", watch: "#29b6f6" };
    return `${colors[d.level] || "#4caf50"}22`;
  }, []);

  const polySideColor = useCallback((d: any) => {
    const colors: Record<string, string> = { critical: "#f44336", stress: "#ff9800", watch: "#29b6f6" };
    return `${colors[d.level] || "#4caf50"}44`;
  }, []);

  // Данные пинов — lodKey в каждом объекте чтобы Three.js пересоздавал объекты при смене LOD
  const pinData = useMemo(() =>
    fields.filter((f) => f.center).map((f) => ({
      id: f.id,
      lod: lodKey,
      lat: f.center[0],
      lng: f.center[1],
      crop: f.crop,
      area_ha: f.area_ha,
      isSelected: f.id === selectedId,
    })),
  [fields, selectedId, lodKey]);

  // LOD: переключение big/small по zoom
  const handleZoom = useCallback((altitude: number) => {
    zoomRef.current = altitude;
    const next = altitude > LOD_THRESHOLD ? "far" : "near";
    setLodKey((prev) => (prev === next ? prev : next));
  }, []);

  // Летим к полю
  useEffect(() => {
    if (!globeRef.current || !selectedId) return;
    const field = fields.find((f) => f.id === selectedId);
    if (!field) return;
    globeRef.current.pointOfView({ lat: field.center[0], lng: field.center[1], altitude: 0.04 }, 1600);
  }, [selectedId, flyToTrigger, fields]);

  // Летим к региону
  useEffect(() => {
    if (!globeRef.current || !regionCenter) return;
    if (selectedId) return;
    globeRef.current.pointOfView({ lat: regionCenter[0], lng: regionCenter[1], altitude: 0.9 }, 1000);
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
        onGlobeZoom={handleZoom}
        onGlobeRotate={handleZoom}
        // LOD: пересоздаём custom layer при смене zoom-уровня
        customLayerData={pinData}
        customThreeObject={(d: any) => {
          const isFar = d.lod === "far";
          const mesh = isFar ? createBigPin(d.isSelected) : createSmallDot(d.isSelected);
          mesh.userData = { fieldData: d };
          return mesh;
        }}
        customThreeObjectUpdate={(obj: any, d: any) => {
          if (globeRef.current?.getCoords) {
            const pos = globeRef.current.getCoords(d.lat, d.lng, 0);
            obj.position.set(pos.x, pos.y, pos.z);
          }
        }}
        onCustomLayerClick={(obj: any) => {
          const d = obj.userData?.fieldData;
          if (!d) return;
          onSelect(d.id);
          if (globeRef.current?.getScreenCoords) {
            const coords = globeRef.current.getScreenCoords(d.lat, d.lng);
            if (coords) {
              const field = fields.find((f) => f.id === d.id);
              if (field) setPopup({ field, x: coords.x, y: coords.y });
            }
          }
        }}
        onCustomLayerHover={() => {}}
        controlGlobe={false}
        animateIn={true}
        width={undefined}
        height={undefined}
        style={{ width: "100%", height: "100%" }}
      />

      {/* HTML-попап */}
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
