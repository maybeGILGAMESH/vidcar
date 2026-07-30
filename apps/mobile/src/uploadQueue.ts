import AsyncStorage from "@react-native-async-storage/async-storage";
import type { ApiClient, CompletedPart, UploadSession } from "@vidcar/api-client";

export type QueuedUpload = {
  id: string;
  surveyId: string;
  uri: string;
  fileName: string;
  size: number;
  contentType: string;
  status: "pending" | "uploading" | "failed" | "completed";
  session?: UploadSession;
  completedParts: CompletedPart[];
  error?: string;
};

export type MobilePartUploader = (
  uri: string,
  url: string,
  partNumber: number,
  partSize: number,
  fileSize: number,
) => Promise<string>;

const STORAGE_KEY = "vidcar:upload-queue";

export class ResumableUploadQueue {
  private items: QueuedUpload[] = [];

  constructor(
    private readonly api: ApiClient,
    private readonly uploadPart: MobilePartUploader,
  ) {}

  async restore() {
    this.items = JSON.parse((await AsyncStorage.getItem(STORAGE_KEY)) ?? "[]") as QueuedUpload[];
    return this.snapshot();
  }

  async enqueue(input: Omit<QueuedUpload, "id" | "status" | "completedParts">) {
    this.items.push({
      ...input,
      id: `${input.fileName}:${input.size}:${Date.now()}`,
      status: "pending",
      completedParts: [],
    });
    await this.persist();
    return this.snapshot();
  }

  snapshot() {
    return this.items.map((item) => ({ ...item, completedParts: [...item.completedParts] }));
  }

  async run(onChange?: (items: QueuedUpload[]) => void) {
    for (const item of this.items.filter((entry) => entry.status !== "completed")) {
      try {
        item.status = "uploading";
        item.error = undefined;
        item.session ??= await this.api.createUploadSession({
          surveyId: item.surveyId,
          fileName: item.fileName,
          size: item.size,
          contentType: item.contentType,
        });
        const done = new Set(item.completedParts.map((part) => part.partNumber));
        for (const part of item.session.parts) {
          if (done.has(part.partNumber)) continue;
          const etag = await this.uploadPart(
            item.uri,
            part.url,
            part.partNumber,
            item.session.partSize,
            item.size,
          );
          item.completedParts.push({ partNumber: part.partNumber, etag });
          await this.persist();
          onChange?.(this.snapshot());
        }
        await this.api.completeUpload(item.session.videoId, item.session.uploadId, item.completedParts);
        item.status = "completed";
      } catch (error) {
        item.status = "failed";
        item.error = error instanceof Error ? error.message : "Upload failed";
      }
      await this.persist();
      onChange?.(this.snapshot());
    }
    return this.snapshot();
  }

  private persist() {
    return AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(this.items));
  }
}
