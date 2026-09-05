"use client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type FieldAnalysis = {
  analysis_id?: string;
  polygon_id: string;
  kpi: any;
  ts: any[];
  anomalies: any[];
  explanations: any[];
  warnings: string[];
  sources?: { satellite?: string; weather?: string; restore?: string };
  stats?: { points?: number; gaps_filled?: number; date_min?: string; date_max?: string };
};

export async function fetchAnalysis(
  pid: string,
  regionId = "rostov",
  opts: { start?: string; end?: string; lat?: number; lon?: number } = {}
): Promise<FieldAnalysis> {
  const r = await fetch(`${API}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      polygon_id: pid,
      region_id: regionId,
      start: opts.start || "2023-05-01",
      end: opts.end || "2023-09-30",
      lat: opts.lat ?? 47.2,
      lon: opts.lon ?? 39.7,
    }),
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  const j = await r.json();
  const t = await fetch(`${API}/api/analyze/${j.analysis_id}/timeseries`).then((x) => x.json());
  const a = await fetch(`${API}/api/analyze/${j.analysis_id}/anomalies`).then((x) => x.json());
  const e = await fetch(`${API}/api/analyze/${j.analysis_id}/explanation`).then((x) => x.json());
  return {
    ...j,
    ts: t.timeseries || [],
    anomalies: a.anomalies || [],
    explanations: e.explanations || [],
  };
}

export type ForecastPoint = { date: string; ndvi: number; lo: number; hi: number };

export async function fetchForecast(analysisId: string, horizon = 14): Promise<ForecastPoint[]> {
  const r = await fetch(`${API}/api/analyze/${analysisId}/forecast?horizon=${horizon}`);
  if (!r.ok) throw new Error(`API ${r.status}`);
  const j = await r.json();
  return j.forecast || [];
}
