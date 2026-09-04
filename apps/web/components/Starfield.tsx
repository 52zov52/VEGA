"use client";
import { useMemo } from "react";

// Генерация звёзд через box-shadow — thousands of random white dots
function generateStars(count: number, seed: number): string {
  const shadows: string[] = [];
  let s = seed;
  const rand = () => { s = (s * 16807 + 0) % 2147483647; return s / 2147483647; };

  for (let i = 0; i < count; i++) {
    const x = Math.round(rand() * 2000);
    const y = Math.round(rand() * 2000);
    const size = rand();
    let color: string;
    if (size > 0.97) {
      color = "#ffffff";       // яркие — белые
    } else if (size > 0.9) {
      color = "#ddeeff";       // голубоватые
    } else if (size > 0.8) {
      color = "#fff8e0";       // желтоватые
    } else {
      color = "#888888";       // тусклые — серые
    }
    const r = size > 0.97 ? 1.5 : size > 0.9 ? 1.2 : size > 0.8 ? 1 : 0.7;
    shadows.push(`${x}px ${y}px 0 ${r}px ${color}`);
  }
  return shadows.join(", ");
}

export default function Starfield() {
  const style = useMemo(() => {
    const stars1 = generateStars(600, 42);    // мелкие
    const stars2 = generateStars(200, 137);   // средние
    const stars3 = generateStars(50, 999);    // яркие

    return {
      position: "absolute" as const,
      inset: 0,
      overflow: "hidden",
      pointerEvents: "none" as const,
      zIndex: 0,
    };
  }, []);

  return (
    <div style={style}>
      {/* Слой 1: мелкие тусклые звёзды */}
      <div style={{
        position: "absolute",
        width: 2,
        height: 2,
        boxShadow: generateStars(600, 42),
        animation: "twinkle 4s ease-in-out infinite alternate",
      }} />
      {/* Слой 2: средние звёзды */}
      <div style={{
        position: "absolute",
        width: 2,
        height: 2,
        boxShadow: generateStars(200, 137),
        animation: "twinkle 6s ease-in-out infinite alternate-reverse",
      }} />
      {/* Слой 3: яркие крупные звёзды */}
      <div style={{
        position: "absolute",
        width: 2,
        height: 2,
        boxShadow: generateStars(50, 999),
        animation: "twinkle 3s ease-in-out infinite alternate",
      }} />
    </div>
  );
}
