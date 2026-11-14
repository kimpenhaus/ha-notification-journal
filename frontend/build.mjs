import { build } from "esbuild";

await build({
  entryPoints: { panel: "src/panel.ts", iconset: "src/iconset.ts" },
  outdir: "../custom_components/notification_journal/frontend",
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  legalComments: "none",
  logLevel: "info",
});
