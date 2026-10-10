/** Test-only portable Chromium setup. Extract one binary without changing archive ownership. */
import { createReadStream, createWriteStream } from 'node:fs';
import { mkdir, chmod, stat, writeFile } from 'node:fs/promises';
import { pipeline } from 'node:stream/promises';
import { createBrotliDecompress } from 'node:zlib';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);

export async function portableBrowser() {
  const depsRoot = path.resolve(process.env.FRONTEND_RUNTIME_DEPS || path.join(import.meta.dirname, 'runtime-deps'));
  const chromiumRoot = path.join(depsRoot, 'node_modules/@sparticuz/chromium');
  const { extract } = require(path.join(depsRoot, 'node_modules/tar-fs'));
  const { default: chromium } = await import(pathToFileURL(path.join(chromiumRoot, 'build/index.js')).href);
  const folder = path.resolve(process.env.FRONTEND_BROWSER_CACHE || path.join(import.meta.dirname, 'browser-bin'));
  const executablePath = path.join(folder, 'chromium');
  await mkdir(folder, { recursive: true });
  try { await stat(executablePath); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    await pipeline(createReadStream(path.join(chromiumRoot, 'bin/chromium.br')),
      createBrotliDecompress(), createWriteStream(executablePath, { mode: 0o700 }));
  }
  await chmod(executablePath, 0o700);
  for (const [archive, destination, witness] of [
    ['swiftshader.tar.br', folder, path.join(folder, 'libGLESv2.so')],
    ['fonts.tar.br', path.join(folder, 'fonts'), path.join(folder, 'fonts/fonts.conf')],
  ]) {
    try { await stat(witness); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      await pipeline(createReadStream(path.join(chromiumRoot, 'bin', archive)),
        createBrotliDecompress(), extract(destination, { chown: false }));
    }
  }
  await writeFile(path.join(folder, 'fonts/fonts.conf'), `<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>${path.join(folder, 'fonts')}</dir><dir>/usr/share/fonts</dir><cachedir>${path.join(folder, 'font-cache')}</cachedir><config></config></fontconfig>`);
  return { executablePath, args: chromium.args,
    env: { ...process.env, FONTCONFIG_PATH: path.join(folder, 'fonts'),
      LD_LIBRARY_PATH: [folder, process.env.LD_LIBRARY_PATH].filter(Boolean).join(':') } };
}
