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

function createPinMesh(isSelected: boolean): THREE.Group {
  const group = new THREE.Group();
  const color = isSelected ? 0xffffff : 0x4caf50;

  // Палочка
  const stickGeo = new THREE.CylinderGeometry(1, 1, 30, 8);
  const stickMat = new THREE.MeshBasicMaterial({ color });
  const stick = new THREE.Mesh(stickGeo, stickMat);
  stick.rotation.x = Math.PI / 2;
  stick.position.z = 15;
  group.add(stick);

  // Шарик сверху
  const headGeo = new THREE.SphereGeometry(6, 16, 16);
  const headMat = new THREE.MeshBasicMaterial({ color: isSelected ? 0x4caf50 : 0x1a1a1a });
  const head = new THREE.Mesh(headGeo, headMat);
  head.position.z = 33;
  group.add(head);

  return group;
}

const MIN_SCALE = 0.0003;
const MAX_SCALE = 0.003;

export default function Globe({ fields, selectedId, onSelect, onAnalyze, regionCenter, flyToTrigger }: Props) {
  const globeRef = useRef<any>(null);
  const [GlobeComp, setGlobeComp] = useState<any>(null);
  const [ready, setReady] = useState(false);
  const [popup, setPopup] = useState<{ field: Field; x: number; y: number } | null>(null);
  const altitudeRef = useRef(0.9);

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

  const pinData = useMemo(() =>
    fields.filter((f) => f.center).map((f) => ({
      id: f.id,
      lat: f.center[0],
      lng: f.center[1],
      crop: f.crop,
      area_ha: f.area_ha,
      isSelected: f.id === selectedId,
    })),
  [fields, selectedId]);

  const handleZoomRotate = useCallback((altitude: number) => {
    altitudeRef.current = altitude;
  }, []);

  useEffect(() => {
    if (!globeRef.current || !selectedId) return;
    const field = fields.find((f) => f.id === selectedId);
    if (!field) return;
    globeRef.current.pointOfView({ lat: field.center[0], lng: field.center[1], altitude: 0.04 }, 1600);
  }, [selectedId, flyToTrigger, fields]);

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
        polygonsData={polygonData}
        polygonGeoJsonGeometry="geoJsonGeometry"
        polygonCapColor={polyCapColor}
        polygonSideColor={polySideColor}
        polygonStrokeColor={(d: any) => d.id === selectedId ? "#ffffffaa" : "transparent"}
        polygonAltitude={(d: any) => d.id === selectedId ? 0.002 : 0.0005}
        polygonStrokeWidth={(d: any) => d.id === selectedId ? 1 : 0}
        onPolygonClick={(d: any) => onSelect(d.id)}
        onGlobeZoom={handleZoomRotate}
        onGlobeRotate={handleZoomRotate}
        customLayerData={pinData}
        customThreeObject={(d: any) => {
          const mesh = createPinMesh(d.isSelected);
          mesh.userData = { fieldData: d };
          return mesh;
        }}
        customThreeObjectUpdate={(obj: any, d: any) => {
          if (globeRef.current?.getCoords) {
            const pos = globeRef.current.getCoords(d.lat, d.lng, 0);
            obj.position.set(pos.x, pos.y, pos.z);
            // Масштаб = f(altitude): дальше = крупнее, ближе = мельче
            const alt = altitudeRef.current;
            const t = Math.min(alt / 1.5, 1);
            const scale = MIN_SCALE + t * (MAX_SCALE - MIN_SCALE);
            obj.scale.set(scale, scale, scale);
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
