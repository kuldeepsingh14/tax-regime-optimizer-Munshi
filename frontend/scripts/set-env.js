/**
 * Writes src/environments/environment.prod.ts from the API_BASE env var.
 *
 * Angular inlines environment.prod.ts at build time, so the API URL would
 * otherwise have to be committed. On Vercel you set API_BASE once in the
 * dashboard and the URL never touches the repo — which also means changing
 * the Render URL is a redeploy, not a code change.
 *
 * If API_BASE is unset (a normal local build) the file is left exactly as is.
 */
const fs = require('fs');
const path = require('path');

const apiBase = (process.env.API_BASE || '').trim().replace(/\/+$/, '');
const target = path.join(__dirname, '..', 'src', 'environments', 'environment.prod.ts');

if (!apiBase) {
  console.log('[set-env] API_BASE not set — leaving environment.prod.ts unchanged.');
  process.exit(0);
}

if (!/^https?:\/\//.test(apiBase)) {
  console.error(`[set-env] API_BASE must start with http:// or https:// — got "${apiBase}"`);
  process.exit(1);
}

fs.writeFileSync(
  target,
  `// GENERATED AT BUILD TIME from the API_BASE env var. Do not edit by hand.\n` +
    `export const environment = {\n` +
    `  production: true,\n` +
    `  apiBase: '${apiBase}',\n` +
    `};\n`,
  'utf8'
);

console.log(`[set-env] apiBase = ${apiBase}`);
