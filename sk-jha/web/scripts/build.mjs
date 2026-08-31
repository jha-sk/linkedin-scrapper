/**
 * Copy the UI into the directory Vercel publishes.
 *
 * The interface lives in `phantom/static/` and is served by the FastAPI app
 * locally. Keeping a second copy here would mean two versions to edit and one
 * of them silently going stale, so the deploy copies from the single source
 * instead.
 *
 * The UI needs no changes to work here: it already fetches relative `/api/*`
 * URLs, which Vercel routes to the proxy function rather than to FastAPI.
 */

import { cp, mkdir, rm, stat } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, '../../phantom/static');
const destination = resolve(here, '../public');

async function main() {
  try {
    await stat(source);
  } catch {
    console.error(
      `Cannot find the UI at ${source}.\n` +
        'On Vercel, set the project Root Directory to "web" and leave the\n' +
        'repository root as the deployment source, so that phantom/static is\n' +
        'included in the build context.',
    );
    process.exit(1);
  }

  await rm(destination, { recursive: true, force: true });
  await mkdir(destination, { recursive: true });

  // index.html is served from the site root; everything else it references
  // lives under /assets, because that is where FastAPI mounts phantom/static
  // locally. Copying the tree flat would leave /assets/* 404-ing here only.
  await cp(source, resolve(destination, 'assets'), { recursive: true });
  await cp(resolve(source, 'index.html'), resolve(destination, 'index.html'));

  console.log(`Copied ${source} -> ${destination}/assets (+ index.html at root)`);
}

await main();
