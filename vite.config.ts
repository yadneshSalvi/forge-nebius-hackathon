import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const proxy = { "/api": "http://127.0.0.1:4402" };
export default defineConfig({
  plugins: [react()],
  root: "web",
  publicDir: "../public",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          icons: ["lucide-react"],
        },
      },
    },
  },
  server: { host: "127.0.0.1", port: 4401, strictPort: true, proxy },
  preview: { host: "127.0.0.1", port: 4401, strictPort: true, proxy },
});
