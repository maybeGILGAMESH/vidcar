"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  ApiClient,
  BrowserUploadStateStore,
  GeoPoint,
  ProcessingResult,
  uploadMultipart,
  uploadStateKey,
} from "@vidcar/api-client";
import { finishLoginFromCallback, startLogin } from "../lib/oidc";

const api = new ApiClient(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000", () =>
  sessionStorage.getItem("access_token"),
);

export default function Home() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map>();
  const marker = useRef<maplibregl.Marker>();
  const [token, setToken] = useState<string | null>(null);
  const [position, setPosition] = useState<GeoPoint | null>(null);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState<string[]>([""]);
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<ProcessingResult[]>([]);
  const [message, setMessage] = useState("Готово к работе");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    finishLoginFromCallback().then(setToken).catch((error: Error) => setMessage(error.message));
    if (!mapContainer.current) return;
    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? "https://demotiles.maplibre.org/style.json",
      center: [37.6173, 55.7558],
      zoom: 10,
    });
    map.current.addControl(new maplibregl.NavigationControl(), "top-right");
    return () => map.current?.remove();
  }, []);

  const locate = () => {
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const point = {
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracyMeters: coords.accuracy,
          bearingDegrees: coords.heading ?? undefined,
        };
        setPosition(point);
        marker.current?.remove();
        marker.current = new maplibregl.Marker({ color: "#ef5b25" })
          .setLngLat([point.longitude, point.latitude])
          .addTo(map.current!);
        map.current?.flyTo({ center: [point.longitude, point.latitude], zoom: 16 });
      },
      (error) => setMessage(`GPS: ${error.message}`),
      { enableHighAccuracy: true },
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!position || !files.length) {
      setMessage("Получите GPS и выберите видео");
      return;
    }
    try {
      const survey = await api.createSurvey({
        title,
        observedAt: new Date().toISOString(),
        location: position,
        notes: notes.filter(Boolean).map((text) => ({ text })),
      });
      const store = new BrowserUploadStateStore();
      const nextResults: ProcessingResult[] = [];
      for (const file of files) {
        setMessage(`Загрузка ${file.name}`);
        const session = await api.createUploadSession({
          surveyId: survey.id,
          fileName: file.name,
          size: file.size,
          contentType: file.type || "application/octet-stream",
        });
        const source = {
          name: file.name,
          size: file.size,
          contentType: file.type,
          slice: (start: number, end: number) => file.slice(start, end),
        };
        const parts = await uploadMultipart(source, session, store, (done, total) =>
          setProgress(Math.round((done / total) * 100)),
        );
        nextResults.push(await api.completeUpload(session.videoId, session.uploadId, parts));
        await store.remove(uploadStateKey(source));
      }
      setResults(nextResults);
      setMessage("Видео загружены и поставлены в обработку");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Неизвестная ошибка");
    }
  };

  const refresh = async () => {
    setResults(await Promise.all(results.map((item) => api.getProcessingResult(item.videoId))));
  };

  return (
    <main>
      <header>
        <div><strong>VIDCAR</strong><span>Полевое обследование</span></div>
        <button type="button" onClick={() => startLogin().catch((e: Error) => setMessage(e.message))}>
          {token ? "Вход выполнен" : "Войти через OIDC"}
        </button>
      </header>
      <section className="grid">
        <div>
          <div ref={mapContainer} className="map" />
          <button className="wide secondary" type="button" onClick={locate}>Получить точный GPS</button>
          {position && (
            <p className="telemetry">
              {position.latitude.toFixed(6)}, {position.longitude.toFixed(6)} · точность ±
              {Math.round(position.accuracyMeters ?? 0)} м · направление{" "}
              {position.bearingDegrees == null ? "н/д" : `${Math.round(position.bearingDegrees)}°`}
            </p>
          )}
        </div>
        <form onSubmit={submit}>
          <h1>Новое обследование</h1>
          <label>Название<input value={title} onChange={(e) => setTitle(e.target.value)} required /></label>
          <label>Видео<input type="file" accept="video/*" multiple onChange={(e) => setFiles([...e.target.files ?? []])} /></label>
          <div className="notes">
            <div><b>Заметки</b><small>{notes.length}/10</small></div>
            {notes.map((note, index) => (
              <div className="note" key={index}>
                <input value={note} maxLength={500} onChange={(e) => setNotes(notes.map((n, i) => i === index ? e.target.value : n))} placeholder={`Заметка ${index + 1}`} />
                {notes.length > 1 && <button type="button" onClick={() => setNotes(notes.filter((_, i) => i !== index))}>×</button>}
              </div>
            ))}
            {notes.length < 10 && <button type="button" className="link" onClick={() => setNotes([...notes, ""])}>+ Добавить заметку</button>}
          </div>
          <button className="wide" type="submit">Создать и загрузить</button>
          <progress max={100} value={progress} />
          <p className="status">{message}</p>
        </form>
      </section>
      {results.length > 0 && (
        <section className="results">
          <div><h2>Обработка</h2><button type="button" onClick={refresh}>Обновить</button></div>
          {results.map((result) => (
            <article key={result.videoId}>
              <span>{result.videoId}</span><b>{result.status}</b>
              {result.downloadUrl && <a href={result.downloadUrl}>Скачать результат</a>}
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
