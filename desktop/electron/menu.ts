/**
 * Application menu. Replaces Electron's default boilerplate menu (the generic
 * File/Edit/View with a "Learn More → electronjs.org" Help) with a small,
 * VideoCraft-specific one: window/zoom controls + DevTools under View, and
 * About / GitHub / issue reporting under Help.
 *
 * Labels are LOCALISED: the renderer owns i18n (tr()), so Shell sends the
 * translated labels here via vc:setMenu on boot and on every language switch
 * (no menu strings duplicated into the main process). DEFAULT_MENU_LABELS is the
 * English fallback applied at startup before the renderer connects.
 */

import { Menu, shell, type MenuItemConstructorOptions } from "electron";

export interface MenuLabels {
  file: string;
  quit: string;
  view: string;
  reload: string;
  devtools: string;
  zoomReset: string;
  zoomIn: string;
  zoomOut: string;
  fullscreen: string;
  help: string;
  about: string;
  github: string;
  reportIssue: string;
}

export const DEFAULT_MENU_LABELS: MenuLabels = {
  file: "File",
  quit: "Quit",
  view: "View",
  reload: "Reload",
  devtools: "Toggle DevTools",
  zoomReset: "Actual Size",
  zoomIn: "Zoom In",
  zoomOut: "Zoom Out",
  fullscreen: "Toggle Fullscreen",
  help: "Help",
  about: "About VideoCraft",
  github: "GitHub",
  reportIssue: "Report Issue",
};

export interface MenuHandlers {
  /** Help → About: show the native about dialog (composed in main). */
  onAbout: () => void;
  /** Help → GitHub: the repo URL. */
  repoUrl: string;
  /** Help → Report Issue: the repo issues URL. */
  issuesUrl: string;
}

/** Build the template from labels + handlers and install it as the app menu. */
export function applyAppMenu(labels: MenuLabels, handlers: MenuHandlers): void {
  const template: MenuItemConstructorOptions[] = [
    {
      label: labels.file,
      submenu: [{ role: "quit", label: labels.quit }],
    },
    {
      label: labels.view,
      submenu: [
        { role: "reload", label: labels.reload },
        { role: "toggleDevTools", label: labels.devtools },
        { type: "separator" },
        { role: "resetZoom", label: labels.zoomReset },
        { role: "zoomIn", label: labels.zoomIn },
        { role: "zoomOut", label: labels.zoomOut },
        { type: "separator" },
        { role: "togglefullscreen", label: labels.fullscreen },
      ],
    },
    {
      label: labels.help,
      submenu: [
        { label: labels.about, click: handlers.onAbout },
        { type: "separator" },
        { label: labels.github, click: () => void shell.openExternal(handlers.repoUrl) },
        { label: labels.reportIssue, click: () => void shell.openExternal(handlers.issuesUrl) },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
