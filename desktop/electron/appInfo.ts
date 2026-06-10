/**
 * App brand identity — author / org / license / homepage / copyright, read once
 * from package.json (the single source that also feeds electron-builder + npm).
 * The About card (Settings) and the native Help → About dialog both render this.
 * Build identity (version / build / commit) is a separate concern — buildInfo.ts.
 */

import { app } from "electron";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export interface AppInfo {
  /** Product display name (brand), not the npm package id. */
  name: string;
  /** Copyright holder / author — package.json `author`. */
  author: string;
  /** GitHub org, derived from the homepage owner segment (the dosmoon brand). */
  org: string;
  /** SPDX license id — package.json `license`. */
  license: string;
  /** Project homepage / repo URL — package.json `homepage`. */
  homepage: string;
  /** Composed "© <years> <author>" line. */
  copyright: string;
}

/**
 * Read the brand fields from package.json (asar root when packaged, the project
 * dir in dev). Unreadable fields degrade to empty strings — the About card just
 * omits the missing line.
 */
export function readAppInfo(): AppInfo {
  let author = "";
  let license = "";
  let homepage = "";
  try {
    const pkg = JSON.parse(readFileSync(join(app.getAppPath(), "package.json"), "utf-8")) as {
      author?: string;
      license?: string;
      homepage?: string;
    };
    if (typeof pkg.author === "string") author = pkg.author;
    if (typeof pkg.license === "string") license = pkg.license;
    if (typeof pkg.homepage === "string") homepage = pkg.homepage;
  } catch {
    // dev partial tree / unreadable — leave brand fields empty.
  }
  // org = the GitHub owner in github.com/<org>/<repo> (single source = the URL).
  const org = homepage.match(/github\.com\/([^/]+)/)?.[1] ?? "";
  // Copyright runs from the project's first year (LICENSE) to the current year.
  const copyright = author ? `© 2025-${new Date().getFullYear()} ${author}` : "";
  // app.getName() is the npm id ("videocraft-desktop") in dev — use the brand.
  return { name: "VideoCraft", author, org, license, homepage, copyright };
}
