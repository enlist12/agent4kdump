/** @type {import('tailwindcss').Config} */
export default {
  content: ["./app/index.html", "./app/src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        panel: "rgb(var(--color-panel) / <alpha-value>)",
        "panel-strong": "rgb(var(--color-panel-strong) / <alpha-value>)",
        border: "rgb(var(--color-border) / <alpha-value>)",
        accent: "rgb(var(--color-accent) / <alpha-value>)",
        crash: "rgb(var(--color-crash) / <alpha-value>)",
        warn: "rgb(var(--color-warn) / <alpha-value>)",
        ok: "rgb(var(--color-ok) / <alpha-value>)"
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Consolas", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"]
      }
    }
  },
  plugins: []
};
