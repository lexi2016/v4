/** Independent test launcher: reads the existing browser and writes only in work/evidence. */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
export async function portableBrowser() {
  const { default: chromium } = await import('../frontend/runtime-deps/node_modules/@sparticuz/chromium/build/index.js');
  const folder = path.join(import.meta.dirname, '../frontend/browser-bin');
  const output = path.join(import.meta.dirname, 'frontend-independent-runtime');
  await mkdir(path.join(output, 'font-cache'), { recursive: true });
  await mkdir(path.join(output, 'tmp'), { recursive: true });
  await writeFile(path.join(output, 'fonts.conf'), `<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>${folder}/fonts</dir><dir>/usr/share/fonts</dir><cachedir>${output}/font-cache</cachedir><config></config></fontconfig>`);
  return { executablePath: path.join(folder, 'chromium'), args: chromium.args,
    env: { ...process.env, TMPDIR: path.join(output, 'tmp'), FONTCONFIG_PATH: output,
      LD_LIBRARY_PATH: [folder, process.env.LD_LIBRARY_PATH].filter(Boolean).join(':') } };
}
