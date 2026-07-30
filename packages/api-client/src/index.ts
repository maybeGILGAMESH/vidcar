export type Note = {
  text: string;
  timestampSeconds?: number;
};

export type GeoPoint = {
  latitude: number;
  longitude: number;
  accuracyMeters?: number;
  bearingDegrees?: number;
};

export type CreateSurveyInput = {
  title?: string;
  observedAt?: string;
  location: GeoPoint;
  notes: Note[];
};

export type Survey = {
  id: string;
  ownerId: string;
  latitude: number;
  longitude: number;
  gpsAccuracyM: number;
  cameraDirectionDeg?: number | null;
  createdAt: string;
};

export type UploadPart = {
  partNumber: number;
  url: string;
};

export type UploadSession = {
  videoId: string;
  uploadId: string;
  objectKey: string;
  partSize: number;
  parts: UploadPart[];
};

export type CompletedPart = {
  partNumber: number;
  etag: string;
};

export type ProcessingStatus =
  | "uploaded"
  | "queued"
  | "claimed"
  | "processing"
  | "uploading_results"
  | "awaiting_finalize"
  | "completed"
  | "failed"
  | "uploading"
  | "created";

export type ProcessingResult = {
  videoId: string;
  status: ProcessingStatus;
  progress?: number;
  message?: string;
  downloadUrl?: string;
  summary?: Record<string, unknown>;
  fileName?: string;
  surveyId?: string;
  startedAt?: string;
};

export type TokenProvider = () => Promise<string | null> | string | null;

async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function sha256Blob(blob: Blob): Promise<string> {
  return sha256Hex(await blob.arrayBuffer());
}

function mapJobState(state: string): ProcessingStatus {
  if (state === "failed_retryable" || state === "failed_terminal") return "failed";
  if (state === "completed") return "completed";
  if (state === "queued") return "queued";
  if (state === "claimed") return "claimed";
  if (state === "processing") return "processing";
  if (state === "uploading_results" || state === "awaiting_finalize") return "uploading_results";
  if (state === "uploaded") return "uploaded";
  if (state === "uploading") return "uploading";
  return "created";
}

/** Rough pipeline progress for UI bars (0..100). */
export function progressForStatus(status: ProcessingStatus, uploadPercent = 0): number {
  switch (status) {
    case "created":
      return 5;
    case "uploading":
      return Math.max(5, Math.min(40, Math.round(uploadPercent * 0.4)));
    case "uploaded":
      return 42;
    case "queued":
      return 52;
    case "claimed":
      return 62;
    case "processing":
      return 78;
    case "uploading_results":
    case "awaiting_finalize":
      return 92;
    case "completed":
      return 100;
    case "failed":
      return 100;
    default:
      return 10;
  }
}

export function statusLabelRu(status: ProcessingStatus): string {
  switch (status) {
    case "created":
      return "Создано";
    case "uploading":
      return "Загрузка на сервер";
    case "uploaded":
      return "Загружено";
    case "queued":
      return "В очереди";
    case "claimed":
      return "Взято в работу";
    case "processing":
      return "Обработка GPU";
    case "uploading_results":
      return "Выгрузка результатов";
    case "awaiting_finalize":
      return "Финализация";
    case "completed":
      return "Готово";
    case "failed":
      return "Ошибка";
    default:
      return status;
  }
}

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly getToken?: TokenProvider,
  ) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = await this.getToken?.();
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      // Local compose demo: API accepts this when DEMO_AUTH_BYPASS=true,
      // and also uses it as the subject when no OIDC proxy is in front.
      "X-User-ID": "demo-operator",
      "X-User-Email": "demo@localhost",
      ...(init?.headers as Record<string, string> | undefined),
    };
    const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers,
    });
    if (!response.ok) {
      throw new Error(`API ${response.status}: ${await response.text()}`);
    }
    return response.json() as Promise<T>;
  }

  async createSurvey(input: CreateSurveyInput): Promise<Survey> {
    if (input.notes.length > 10) throw new Error("A survey supports at most 10 notes");
    const accuracy = Math.max(1, Number(input.location.accuracyMeters ?? 30));
    const notes = input.notes
      .map((n) => n.text.trim())
      .filter(Boolean)
      .map((text) => ({ text }));
    if (input.title?.trim()) {
      notes.unshift({ text: `title: ${input.title.trim()}` });
    }
    const raw = await this.request<{
      id: string;
      owner_id: string;
      latitude: number;
      longitude: number;
      gps_accuracy_m: number;
      camera_direction_deg?: number | null;
      created_at: string;
    }>("/api/v1/surveys", {
      method: "POST",
      body: JSON.stringify({
        latitude: input.location.latitude,
        longitude: input.location.longitude,
        gps_accuracy_m: accuracy,
        camera_direction_deg: input.location.bearingDegrees ?? null,
        notes,
      }),
    });
    return {
      id: raw.id,
      ownerId: raw.owner_id,
      latitude: raw.latitude,
      longitude: raw.longitude,
      gpsAccuracyM: raw.gps_accuracy_m,
      cameraDirectionDeg: raw.camera_direction_deg,
      createdAt: raw.created_at,
    };
  }

  async createUploadSession(input: {
    surveyId: string;
    fileName: string;
    size: number;
    contentType: string;
    sha256: string;
    partSizeBytes?: number;
  }): Promise<UploadSession> {
    const raw = await this.request<{
      video_id: string;
      upload_id: string;
      object_key: string;
      part_size_bytes: number;
      part_urls: Array<{ part_number: number; url: string }>;
    }>("/api/v1/videos/upload-sessions", {
      method: "POST",
      body: JSON.stringify({
        survey_id: input.surveyId,
        filename: input.fileName,
        content_type: input.contentType || "video/mp4",
        size_bytes: input.size,
        sha256: input.sha256,
        part_size_bytes: input.partSizeBytes ?? 8 * 1024 * 1024,
      }),
    });
    return {
      videoId: raw.video_id,
      uploadId: raw.upload_id,
      objectKey: raw.object_key,
      partSize: raw.part_size_bytes,
      parts: raw.part_urls.map((part) => ({
        partNumber: part.part_number,
        url: part.url,
      })),
    };
  }

  async completeUpload(videoId: string, _uploadId: string, parts: CompletedPart[]): Promise<ProcessingResult> {
    const raw = await this.request<{ id: string; state: string }>(`/api/v1/videos/${videoId}/complete-upload`, {
      method: "POST",
      body: JSON.stringify({
        parts: parts.map((part) => ({
          part_number: part.partNumber,
          etag: part.etag,
        })),
      }),
    });
    return {
      videoId: raw.id,
      status: mapJobState(raw.state),
      progress: progressForStatus(mapJobState(raw.state)),
      message: `state=${raw.state}`,
    };
  }

  async getProcessingResult(videoId: string): Promise<ProcessingResult> {
    try {
      const raw = await this.request<{
        video_id: string;
        summary?: Record<string, unknown>;
        artifacts?: unknown[];
      }>(`/api/v1/videos/${videoId}/result`);
      return {
        videoId: raw.video_id,
        status: "completed",
        progress: 100,
        summary: raw.summary,
        message: "result ready",
        downloadUrl: `/api/v1/videos/${videoId}/download`,
      };
    } catch (error) {
      if (!(error instanceof Error) || !error.message.includes("API 404")) {
        throw error;
      }
      const video = await this.request<{ id: string; state: string; filename?: string }>(
        `/api/v1/videos/${videoId}`,
      );
      const status = mapJobState(video.state);
      return {
        videoId: video.id,
        status,
        progress: progressForStatus(status),
        message: `state=${video.state}`,
        fileName: video.filename,
      };
    }
  }
}

export * from "./multipart";
