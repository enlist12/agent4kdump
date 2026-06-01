import { mockEvents, mockSession } from "./mock";
import type {
  AnalysisConfigPayload,
  AnalysisEvent,
  AnalysisSession,
  EnvSettingsResponse,
  UploadVmcoreResponse
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    ...init
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listSessions(): Promise<AnalysisSession[]> {
  try {
    const sessions = await request<AnalysisSession[]>("/api/sessions");
    return sessions.length ? sessions : [mockSession];
  } catch {
    return [mockSession];
  }
}

export async function getSession(sessionId: string): Promise<AnalysisSession> {
  if (sessionId === mockSession.id) {
    return mockSession;
  }
  return request<AnalysisSession>(`/api/sessions/${sessionId}`);
}

export async function createSession(
  name: string,
  config: AnalysisConfigPayload
): Promise<AnalysisSession> {
  return request<AnalysisSession>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ name, config })
  });
}

export async function runSession(sessionId: string, dryRun = false): Promise<AnalysisSession> {
  return request<AnalysisSession>(`/api/sessions/${sessionId}/run`, {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun })
  });
}

export async function cancelSession(sessionId: string): Promise<AnalysisSession> {
  return request<AnalysisSession>(`/api/sessions/${sessionId}/cancel`, {
    method: "POST"
  });
}

export async function getEnvSettings(): Promise<EnvSettingsResponse> {
  return request<EnvSettingsResponse>("/api/settings/env");
}

export async function updateEnvSettings(
  values: Record<string, string | null>
): Promise<EnvSettingsResponse> {
  return request<EnvSettingsResponse>("/api/settings/env", {
    method: "PUT",
    body: JSON.stringify({ values })
  });
}

export async function loadEnvFile(path: string): Promise<EnvSettingsResponse> {
  return request<EnvSettingsResponse>("/api/settings/env/load", {
    method: "POST",
    body: JSON.stringify({ path })
  });
}

export function uploadVmcore(
  file: File,
  onProgress?: (progress: number) => void
): Promise<UploadVmcoreResponse> {
  const form = new FormData();
  form.append("file", file);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/uploads/vmcore`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as UploadVmcoreResponse);
        return;
      }
      reject(new Error(xhr.responseText || `Upload failed: ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Upload failed due to a network error."));
    xhr.send(form);
  });
}

export function subscribeSessionEvents(
  sessionId: string,
  onEvent: (event: AnalysisEvent) => void
): () => void {
  if (sessionId === mockSession.id || typeof EventSource === "undefined") {
    mockEvents.forEach((event, index) => {
      window.setTimeout(() => onEvent(event), index * 800);
    });
    return () => undefined;
  }

  const source = new EventSource(`${API_BASE_URL}/api/sessions/${sessionId}/events`);
  source.onmessage = (message) => {
    onEvent(JSON.parse(message.data) as AnalysisEvent);
  };
  source.onerror = () => {
    source.close();
  };
  return () => source.close();
}
