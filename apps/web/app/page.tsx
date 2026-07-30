"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  ApiClient,
  BrowserUploadStateStore,
  GeoPoint,
  ProcessingResult,
  ProcessingStatus,
  progressForStatus,
  sha256Blob,
  statusLabelRu,
  uploadMultipart,
  uploadStateKey,
} from "@vidcar/api-client";
import { clearAuth, finishLoginFromCallback, startLogin } from "../lib/oidc";

const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";
const api = new ApiClient(apiBase, () => localStorage.getItem("access_token") ?? sessionStorage.getItem("access_token"));

const JOBS_KEY = "vidcar.jobs.v1";
const POSITION_KEY = "vidcar.position.v1";
const DRAFT_KEY = "vidcar.draft.v1";

type TrackedJob = ProcessingResult & {
  fileName: string;
  surveyId?: string;
  startedAt: string;
};

function loadJobs(): TrackedJob[] {
  try {
    const raw = localStorage.getItem(JOBS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as TrackedJob[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveJobs(jobs: TrackedJob[]) {
  localStorage.setItem(JOBS_KEY, JSON.stringify(jobs.slice(0, 40)));
}

function isTerminal(status: ProcessingStatus) {
  return status === "completed" || status === "failed";
}

export default function Home() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map>();
  const marker = useRef<maplibregl.Marker>();
  const [token, setToken] = useState<string | null>(null);
  const [position, setPosition] = useState<GeoPoint | null>(null);
  const [positionSource, setPositionSource] = useState<"map" | "gps" | null>(null);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState<string[]>([""]);
  const [files, setFiles] = useState<File[]>([]);
  const [jobs, setJobs] = useState<TrackedJob[]>([]);
  const [message, setMessage] = useState("Кликните по карте, чтобы поставить точку");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [busy, setBusy] = useState(false);

  const placeAt = useCallback((point: GeoPoint, source: "map" | "gps") => {
    setPosition(point);
    setPositionSource(source);
    localStorage.setItem(POSITION_KEY, JSON.stringify({ point, source }));
    if (!map.current) return;
    marker.current?.remove();
    marker.current = new maplibregl.Marker({ color: "#ef5b25" })
      .setLngLat([point.longitude, point.latitude])
      .addTo(map.current);
  }, []);

  // Restore session, draft, jobs, map point
  useEffect(() => {
    finishLoginFromCallback()
      .then((value) => {
        setToken(value);
        if (!value && localStorage.getItem("vidcar.demoSession") === "1") {
          setToken("demo-local-token");
        }
      })
      .catch((error: Error) => setMessage(error.message));

    const restoredJobs = loadJobs();
    if (restoredJobs.length) {
      setJobs(restoredJobs);
      setMessage(`Восстановлено заданий: ${restoredJobs.length}`);
    }

    try {
      const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null") as
        | { title?: string; notes?: string[] }
        | null;
      if (draft?.title) setTitle(draft.title);
      if (draft?.notes?.length) setNotes(draft.notes);
    } catch {
      /* ignore */
    }

    try {
      const saved = JSON.parse(localStorage.getItem(POSITION_KEY) || "null") as
        | { point: GeoPoint; source: "map" | "gps" }
        | null;
      if (saved?.point) {
        setPosition(saved.point);
        setPositionSource(saved.source);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ title, notes }));
  }, [title, notes]);

  useEffect(() => {
    saveJobs(jobs);
  }, [jobs]);

  // Map init + restore marker
  useEffect(() => {
    if (!mapContainer.current) return;
    const instance = new maplibregl.Map({
      container: mapContainer.current,
      style: process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? "/map-style.json",
      center: [37.6173, 55.7558],
      zoom: 10,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");
    instance.getCanvas().style.cursor = "crosshair";
    const onClick = (event: maplibregl.MapMouseEvent) => {
      placeAt(
        {
          latitude: event.lngLat.lat,
          longitude: event.lngLat.lng,
          accuracyMeters: 30,
        },
        "map",
      );
      setMessage("Точка на карте выбрана — GPS-доступ не нужен");
    };
    instance.on("click", onClick);
    instance.on("load", () => {
      try {
        const saved = JSON.parse(localStorage.getItem(POSITION_KEY) || "null") as
          | { point: GeoPoint; source: "map" | "gps" }
          | null;
        if (saved?.point) {
          marker.current?.remove();
          marker.current = new maplibregl.Marker({ color: "#ef5b25" })
            .setLngLat([saved.point.longitude, saved.point.latitude])
            .addTo(instance);
          instance.jumpTo({ center: [saved.point.longitude, saved.point.latitude], zoom: 12 });
        }
      } catch {
        /* ignore */
      }
    });
    return () => {
      instance.off("click", onClick);
      instance.remove();
      map.current = undefined;
      marker.current = undefined;
    };
  }, [placeAt]);

  // Auto-poll active jobs
  useEffect(() => {
    const active = jobs.filter((job) => !isTerminal(job.status));
    if (!active.length) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const updates = await Promise.all(
          active.map(async (job) => {
            const next = await api.getProcessingResult(job.videoId);
            return {
              ...job,
              ...next,
              fileName: job.fileName || next.fileName || job.videoId,
              startedAt: job.startedAt,
              surveyId: job.surveyId,
              progress: next.progress ?? progressForStatus(next.status),
            } satisfies TrackedJob;
          }),
        );
        if (cancelled) return;
        setJobs((prev) => {
          const byId = new Map(updates.map((item) => [item.videoId, item]));
          return prev.map((item) => byId.get(item.videoId) ?? item);
        });
      } catch (error) {
        if (!cancelled) {
          setMessage(error instanceof Error ? error.message : "Ошибка опроса статуса");
        }
      }
    };
    tick();
    const id = window.setInterval(tick, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [jobs.map((j) => `${j.videoId}:${j.status}`).join("|")]);

  const locate = () => {
    if (!navigator.geolocation) {
      setMessage("Геолокация недоступна — кликните по карте");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const point = {
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracyMeters: coords.accuracy,
          bearingDegrees: coords.heading ?? undefined,
        };
        placeAt(point, "gps");
        map.current?.flyTo({ center: [point.longitude, point.latitude], zoom: 16 });
        setMessage("Точный GPS получен");
      },
      (error) => setMessage(`GPS недоступен (${error.message}). Кликните по карте.`),
      { enableHighAccuracy: true },
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!position || !files.length) {
      setMessage("Поставьте точку на карте (или GPS) и выберите видео");
      return;
    }
    setBusy(true);
    setUploadProgress(0);
    try {
      if (!token) {
        localStorage.setItem("vidcar.demoSession", "1");
        localStorage.setItem("access_token", "demo-local-token");
        setToken("demo-local-token");
      }
      setMessage("Создаём обследование…");
      const survey = await api.createSurvey({
        title,
        observedAt: new Date().toISOString(),
        location: position,
        notes: notes.filter(Boolean).map((text) => ({ text })),
      });
      const store = new BrowserUploadStateStore();
      const created: TrackedJob[] = [];
      for (const file of files) {
        const startedAt = new Date().toISOString();
        setMessage(`Хешируем ${file.name}…`);
        const digest = await sha256Blob(file);
        setMessage(`Загрузка ${file.name}`);
        const session = await api.createUploadSession({
          surveyId: survey.id,
          fileName: file.name,
          size: file.size,
          contentType: file.type || "video/mp4",
          sha256: digest,
        });
        // Show in-flight upload row immediately (survives F5 after complete).
        setJobs((prev) => {
          const row: TrackedJob = {
            videoId: session.videoId,
            fileName: file.name,
            surveyId: survey.id,
            status: "uploading",
            progress: progressForStatus("uploading", 0),
            startedAt,
            message: "upload in progress",
          };
          const next = [row, ...prev.filter((item) => item.videoId !== session.videoId)];
          saveJobs(next);
          return next;
        });
        const source = {
          name: file.name,
          size: file.size,
          contentType: file.type || "video/mp4",
          slice: (start: number, end: number) => file.slice(start, end),
        };
        const parts = await uploadMultipart(source, session, store, (done, total) => {
          const pct = Math.round((done / total) * 100);
          setUploadProgress(pct);
          setJobs((prev) =>
            prev.map((item) =>
              item.videoId === session.videoId
                ? {
                    ...item,
                    status: "uploading",
                    progress: progressForStatus("uploading", pct),
                    message: `загрузка ${pct}%`,
                  }
                : item,
            ),
          );
        });
        const completed = await api.completeUpload(session.videoId, session.uploadId, parts);
        const row: TrackedJob = {
          ...completed,
          fileName: file.name,
          surveyId: survey.id,
          startedAt,
          progress: completed.progress ?? progressForStatus(completed.status),
        };
        created.push(row);
        setJobs((prev) => {
          const next = [row, ...prev.filter((item) => item.videoId !== row.videoId)];
          saveJobs(next);
          return next;
        });
        await store.remove(uploadStateKey(source));
      }
      setUploadProgress(100);
      setMessage(`Загружено: ${created.length}. Обработка идёт в фоне — можно обновлять страницу.`);
      setFiles([]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Неизвестная ошибка");
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    if (!jobs.length) return;
    setMessage("Обновляем статусы…");
    const next = await Promise.all(
      jobs.map(async (job) => {
        const remote = await api.getProcessingResult(job.videoId);
        return {
          ...job,
          ...remote,
          fileName: job.fileName || remote.fileName || job.videoId,
          startedAt: job.startedAt,
          surveyId: job.surveyId,
          progress: remote.progress ?? progressForStatus(remote.status),
        } satisfies TrackedJob;
      }),
    );
    setJobs(next);
    setMessage("Статусы обновлены");
  };

  const clearFinished = () => {
    setJobs((prev) => prev.filter((job) => !isTerminal(job.status)));
  };

  const logout = () => {
    clearAuth();
    setToken(null);
    setMessage("Сессия сброшена (задания на странице сохранены локально)");
  };

  return (
    <main>
      <header>
        <div>
          <strong>VIDCAR</strong>
          <span>Полевое обследование</span>
        </div>
        <div className="header-actions">
          {token ? (
            <>
              <span className="badge">Вход сохранён</span>
              <button type="button" className="secondary" onClick={logout}>
                Выйти
              </button>
            </>
          ) : (
            <button type="button" onClick={() => startLogin().then(() => setToken(localStorage.getItem("access_token"))).catch((e: Error) => setMessage(e.message))}>
              Войти
            </button>
          )}
        </div>
      </header>
      <section className="grid">
        <div>
          <div ref={mapContainer} className="map" />
          <p className="map-hint">Клик по карте ставит координаты. GPS-доступ не обязателен.</p>
          <button className="wide secondary" type="button" onClick={locate}>
            Получить точный GPS (опционально)
          </button>
          {position && (
            <p className="telemetry">
              {position.latitude.toFixed(6)}, {position.longitude.toFixed(6)} ·{" "}
              {positionSource === "map" ? "точка с карты" : "GPS"} · точность ±
              {Math.round(position.accuracyMeters ?? 0)} м · направление{" "}
              {position.bearingDegrees == null ? "н/д" : `${Math.round(position.bearingDegrees)}°`}
            </p>
          )}
        </div>
        <form onSubmit={submit}>
          <h1>Новое обследование</h1>
          <label>
            Название
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label>
            Видео
            <input
              type="file"
              accept="video/*"
              multiple
              onChange={(e) => setFiles([...(e.target.files ?? [])])}
            />
          </label>
          <div className="notes">
            <div>
              <b>Заметки</b>
              <small>{notes.length}/10</small>
            </div>
            {notes.map((note, index) => (
              <div className="note" key={index}>
                <input
                  value={note}
                  maxLength={500}
                  onChange={(e) => setNotes(notes.map((n, i) => (i === index ? e.target.value : n)))}
                  placeholder={`Заметка ${index + 1}`}
                />
                {notes.length > 1 && (
                  <button type="button" onClick={() => setNotes(notes.filter((_, i) => i !== index))}>
                    ×
                  </button>
                )}
              </div>
            ))}
            {notes.length < 10 && (
              <button type="button" className="link" onClick={() => setNotes([...notes, ""])}>
                + Добавить заметку
              </button>
            )}
          </div>
          <button className="wide" type="submit" disabled={busy}>
            {busy ? "Загрузка…" : "Создать и загрузить"}
          </button>
          <div className="progress-block">
            <div className="progress-meta">
              <span>Загрузка на сервер</span>
              <span>{uploadProgress}%</span>
            </div>
            <progress max={100} value={uploadProgress} />
          </div>
          <p className="status">{message}</p>
        </form>
      </section>

      <section className="results">
        <div>
          <h2>Обработка {jobs.length ? `(${jobs.length})` : ""}</h2>
          <div className="header-actions">
            <button type="button" className="secondary" onClick={refresh} disabled={!jobs.length}>
              Обновить
            </button>
            <button type="button" className="secondary" onClick={clearFinished}>
              Убрать готовые
            </button>
          </div>
        </div>
        {!jobs.length && <p className="empty">Пока нет сохранённых видео. После загрузки они останутся и после F5.</p>}
        {jobs.map((job) => {
          const pct = job.progress ?? progressForStatus(job.status, uploadProgress);
          return (
            <article key={job.videoId} className="job-card">
              <div className="job-head">
                <div>
                  <b>{job.fileName}</b>
                  <small className="mono">{job.videoId}</small>
                </div>
                <b className={job.status === "failed" ? "bad" : job.status === "completed" ? "ok" : ""}>
                  {statusLabelRu(job.status)}
                </b>
              </div>
              <div className="progress-block">
                <div className="progress-meta">
                  <span>{pct}%</span>
                  <span>{job.message || ""}</span>
                </div>
                <progress max={100} value={pct} />
              </div>
              {job.downloadUrl && (
                <a href={job.downloadUrl} target="_blank" rel="noreferrer">
                  Скачать результат
                </a>
              )}
            </article>
          );
        })}
      </section>
    </main>
  );
}
