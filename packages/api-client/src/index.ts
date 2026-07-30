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
  title: string;
  observedAt: string;
  location: GeoPoint;
  notes: Note[];
};

export type Survey = CreateSurveyInput & {
  id: string;
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
  | "failed";

export type ProcessingResult = {
  videoId: string;
  status: ProcessingStatus;
  progress?: number;
  message?: string;
  downloadUrl?: string;
};

export type TokenProvider = () => Promise<string | null> | string | null;

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly getToken?: TokenProvider,
  ) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = await this.getToken?.();
    const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    });
    if (!response.ok) {
      throw new Error(`API ${response.status}: ${await response.text()}`);
    }
    return response.json() as Promise<T>;
  }

  createSurvey(input: CreateSurveyInput): Promise<Survey> {
    if (input.notes.length > 10) throw new Error("A survey supports at most 10 notes");
    return this.request("/api/v1/surveys", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  createUploadSession(input: {
    surveyId: string;
    fileName: string;
    size: number;
    contentType: string;
  }): Promise<UploadSession> {
    return this.request("/api/v1/videos/upload-sessions", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  completeUpload(videoId: string, uploadId: string, parts: CompletedPart[]) {
    return this.request<ProcessingResult>(`/api/v1/videos/${videoId}/complete-upload`, {
      method: "POST",
      body: JSON.stringify({ uploadId, parts }),
    });
  }

  getProcessingResult(videoId: string): Promise<ProcessingResult> {
    return this.request(`/api/v1/videos/${videoId}/processing-result`);
  }
}

export * from "./multipart";
