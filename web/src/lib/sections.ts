import type { LucideIcon } from "lucide-react";
import { Archive, EyeOff, FileCog, FilePen, Layers, ListChecks } from "lucide-react";
import type { FolderCard, FolderInfo } from "@/lib/types";

/** The tabs of a set's page, in order; each is `/folders/<label>/<id>`. */
export const SECTIONS = [
  { id: "conversion", label: "Conversion", icon: FileCog },
  { id: "matching", label: "Matching & 1G1R", icon: ListChecks },
  { id: "updates", label: "Updates & DLC", icon: Layers },
  { id: "rename", label: "Rename", icon: FilePen },
  { id: "discarded", label: "Discarded", icon: Archive },
  { id: "ignored", label: "Ignored", icon: EyeOff },
] as const satisfies readonly { id: string; label: string; icon: LucideIcon }[];

export type SectionId = (typeof SECTIONS)[number]["id"];

/** The tabs this set has: Updates only on title-ID sets (Switch). */
export function setSections(folder: FolderInfo) {
  return SECTIONS.filter((s) => s.id !== "updates" || folder.title_ids);
}

export const needsConversion = (f: FolderCard) => f.progress.to_convert > 0;

/** Where a set opens from Home and the sidebar: conversion work comes first (the same test as
 * Home's badge and border), so a set needing both opens Conversion. */
export function openingSection(folder: FolderCard): SectionId {
  return needsConversion(folder) ? "conversion" : "matching";
}

/** The page has nothing left to do (a check on its tab). Conversion: every file in the
 * target format and the files checked; Matching & 1G1R: nothing left to process and no scan
 * due; Updates & DLC: scanned and nothing to discard (a newer release or an unread version
 * is no to-do); Rename: converted, scanned and nothing proposed. A set without ROM files has nothing done yet; Discarded and Ignored are
 * never a to-do. */
export function sectionDone(folder: FolderCard, section: SectionId): boolean {
  if (folder.summary.roms === 0) return false;
  if (section === "conversion") return !needsConversion(folder) && folder.needs !== "check";
  if (section === "matching") return folder.progress.to_process === 0 && folder.needs === null;
  if (section === "updates")
    return folder.updates && folder.needs === null ? !updatesLeft(folder) : false;
  if (section === "rename")
    return !needsConversion(folder) && folder.needs === null && !renamesLeft(folder);
  return false;
}

/** Files the set's naming template proposes to rename: the Rename tab's to-do (none while
 * the set keeps its names). */
export const renamesLeft = (folder: FolderCard) => (folder.rename?.proposed ?? 0) > 0;

/** Older updates proposed for discarded/ (title-ID sets): the Updates & DLC tab's to-do. */
export const updatesLeft = (folder: FolderCard) => (folder.updates?.proposed ?? 0) > 0;

/** Nothing left to do on the set at all: every to-do tab is done (Updates & DLC only on
 * title-ID sets). */
export const folderDone = (folder: FolderCard) =>
  sectionDone(folder, "conversion") &&
  sectionDone(folder, "matching") &&
  (folder.updates === null || sectionDone(folder, "updates")) &&
  sectionDone(folder, "rename");

/** The set's state, the colour of its platform badge: an error, else a warning (the card's
 * messages), else done or work left. */
export type FolderState = "bad" | "warn" | "done" | "work";

export function folderState(folder: FolderCard): FolderState {
  if (folder.warnings.some((w) => w.level === "bad")) return "bad";
  if (folder.warnings.some((w) => w.level === "warn")) return "warn";
  return folderDone(folder) ? "done" : "work";
}

export const sectionPath = (label: string, section: SectionId) => `/folders/${label}/${section}`;
