import { QueryClient, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  Conversion,
  DatRow,
  DatSource,
  Discarded,
  FolderCard,
  FolderDetail,
  Game,
  KeyStatus,
  Meta,
  Missing,
  Notification,
  Run,
  SettingsData,
  Statistics,
  UnmatchedFile,
  Updates,
} from "@/lib/types";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } },
});

export const keys = {
  meta: ["meta"] as const,
  folders: ["folders"] as const,
  statistics: ["statistics"] as const,
  missing: (label: string, source: string) => ["missing", label, source] as const,
  folder: (label: string) => ["folder", label] as const,
  games: (label: string) => ["games", label] as const,
  conversion: (label: string) => ["conversion", label] as const,
  unmatched: (label: string) => ["unmatched", label] as const,
  discarded: (label: string) => ["discarded", label] as const,
  updates: (label: string) => ["updates", label] as const,
  run: (label: string) => ["run", label] as const,
  settings: ["settings"] as const,
  dats: ["dats"] as const,
  titledbFiles: ["titledb-files"] as const,
  datSources: ["dat-sources"] as const,
  consoleKeys: ["console-keys"] as const,
  notifications: ["notifications"] as const,
};

export const useMeta = () =>
  useQuery({ queryKey: keys.meta, queryFn: () => api<Meta>("/meta"), staleTime: Infinity });
/** Every set; polled while one of them is scanning, converting, applying or restoring. */
export const useFolders = () =>
  useQuery({
    queryKey: keys.folders,
    queryFn: () => api<FolderCard[]>("/folders"),
    refetchInterval: (query) =>
      query.state.data?.some((f) => f.scan?.status === "running" || f.converting || f.running)
        ? (queryClient.getQueryData<Meta>(keys.meta)?.ui.poll_interval_ms ?? false)
        : false,
  });
/** One set's Home card (from the same polled list). */
export function useFolderCard(label: string) {
  return useFolders().data?.find((f) => f.label === label);
}
export const useSettingsData = () =>
  useQuery({ queryKey: keys.settings, queryFn: () => api<SettingsData>("/settings") });
export const useDats = () =>
  useQuery({ queryKey: keys.dats, queryFn: () => api<DatRow[]>("/dats") });
/** Every titledb region file ("US.en"), read only when asked for (it is a download). */
export const useTitledbFiles = (enabled: boolean) =>
  useQuery({
    queryKey: keys.titledbFiles,
    queryFn: () => api<string[]>("/titledb/files"),
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
  });
export const useConsoleKeys = () =>
  useQuery({ queryKey: keys.consoleKeys, queryFn: () => api<KeyStatus>("/keys") });
export const useGames = (label: string) =>
  useQuery({ queryKey: keys.games(label), queryFn: () => api<Game[]>(`/folders/${label}/games`) });

export const useConversion = (label: string) =>
  useQuery({
    queryKey: keys.conversion(label),
    queryFn: () => api<Conversion>(`/folders/${label}/conversion`),
  });

export const useUnmatched = (label: string) =>
  useQuery({
    queryKey: keys.unmatched(label),
    queryFn: () => api<UnmatchedFile[]>(`/folders/${label}/unmatched`),
  });

export const useDiscarded = (label: string) =>
  useQuery({
    queryKey: keys.discarded(label),
    queryFn: () => api<Discarded>(`/folders/${label}/discarded`),
  });

export const useUpdates = (label: string, enabled: boolean) =>
  useQuery({
    queryKey: keys.updates(label),
    queryFn: () => api<Updates>(`/folders/${label}/updates`),
    enabled,
  });

/** The latest scans and runs: polled often while one runs, now and then otherwise (a run
 * may start in another tab). */
export const useNotifications = () =>
  useQuery({
    queryKey: keys.notifications,
    queryFn: () => api<Notification[]>("/notifications"),
    refetchInterval: (query) => {
      const ui = queryClient.getQueryData<Meta>(keys.meta)?.ui;
      if (!ui) return false;
      return query.state.data?.some((n) => n.status === "running")
        ? ui.poll_interval_ms
        : ui.notifications.idle_poll_ms;
    },
  });

/** The folder's latest apply or restore; polled while it runs. */
export function useRun(label: string, pollMs: number | false) {
  return useQuery({
    queryKey: keys.run(label),
    queryFn: () => api<Run | null>(`/folders/${label}/run`),
    refetchInterval: (query) => (query.state.data?.status === "running" ? pollMs : false),
  });
}

export function useFolder(label: string, pollMs: number | false) {
  return useQuery({
    queryKey: keys.folder(label),
    queryFn: () => api<FolderDetail>(`/folders/${label}`),
    refetchInterval: (query) => (query.state.data?.scan?.status === "running" ? pollMs : false),
  });
}

/** After anything that changes a folder's data, everything that shows it is stale. */
export function invalidateFolder(label: string) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: keys.folder(label) }),
    queryClient.invalidateQueries({ queryKey: keys.games(label) }),
    queryClient.invalidateQueries({ queryKey: keys.conversion(label) }),
    queryClient.invalidateQueries({ queryKey: keys.unmatched(label) }),
    queryClient.invalidateQueries({ queryKey: keys.discarded(label) }),
    queryClient.invalidateQueries({ queryKey: keys.updates(label) }),
    queryClient.invalidateQueries({ queryKey: keys.run(label) }),
    queryClient.invalidateQueries({ queryKey: keys.folders }),
    queryClient.invalidateQueries({ queryKey: keys.notifications }),
  ]);
}

export const useDatSources = () =>
  useQuery({ queryKey: keys.datSources, queryFn: () => api<DatSource[]>("/dat-sources") });

export const useStatistics = () =>
  useQuery({ queryKey: keys.statistics, queryFn: () => api<Statistics>("/statistics") });

export const useMissing = (label: string, source: string) =>
  useQuery({
    queryKey: keys.missing(label, source),
    queryFn: () => api<Missing>(`/statistics/${label}/${source}/missing`),
  });
