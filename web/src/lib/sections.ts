import type { LucideIcon } from "lucide-react";
import { Archive, FileCog, ListChecks } from "lucide-react";
import type { FolderCard } from "@/lib/types";

/** The tabs of a set's page, in order; each is `/folders/<label>/<id>`. */
export const SECTIONS = [
  { id: "conversion", label: "Conversion", icon: FileCog },
  { id: "matching", label: "Matching & 1G1R", icon: ListChecks },
  { id: "discarded", label: "Discarded", icon: Archive },
] as const satisfies readonly { id: string; label: string; icon: LucideIcon }[];

export type SectionId = (typeof SECTIONS)[number]["id"];

export const needsConversion = (f: FolderCard) => f.progress.to_convert > 0;

/** Where a set opens from Home and the sidebar: conversion work comes first (the same test as
 * Home's badge and border), so a set needing both opens Conversion. */
export function openingSection(folder: FolderCard): SectionId {
  return needsConversion(folder) ? "conversion" : "matching";
}

export const sectionPath = (label: string, section: SectionId) => `/folders/${label}/${section}`;
