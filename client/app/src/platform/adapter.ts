type PickPathType = "file" | "dir";

declare global {
  interface Window {
    __TAURI__?: unknown;
  }
}

export interface PlatformAdapter {
  kind: "browser" | "desktop";
  pickPath: (type: PickPathType) => Promise<string | null>;
  openUrl: (url: string) => Promise<void>;
  getBaseUrl: () => string;
}

async function desktopPickPath(type: PickPathType): Promise<string | null> {
  const dialog = await import("@tauri-apps/api/dialog");
  const result = await dialog.open({
    directory: type === "dir",
    multiple: false
  });
  return Array.isArray(result) ? result[0] ?? null : result;
}

async function desktopOpenUrl(url: string): Promise<void> {
  const shell = await import("@tauri-apps/api/shell");
  await shell.open(url);
}

export const platform: PlatformAdapter = {
  kind: window.__TAURI__ ? "desktop" : "browser",

  async pickPath(type) {
    if (window.__TAURI__) {
      return desktopPickPath(type);
    }
    return window.prompt(
      `Enter the absolute ${type === "dir" ? "directory" : "file"} path that the analysis service can access:`
    );
  },

  async openUrl(url) {
    if (window.__TAURI__) {
      await desktopOpenUrl(url);
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  },

  getBaseUrl() {
    return import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  }
};
