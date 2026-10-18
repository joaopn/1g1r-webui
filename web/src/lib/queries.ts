import { QueryClient, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  Conversion,
  DatRow,
  Discarded,
  FolderCard,
  FolderDetail,
  Game,
  KeyStatus,
  Meta,
  Run,
  SettingsData,
  UnmatchedFile,
} from "@/lib/types";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } },
});

export const keys = {
  meta: ["meta"] as const,
  folders: ["folders"] as const,
  folder: (label: string) => ["folder", label] as const,
  games: (label: string) => ["games", label] as const,
  conversion: (label: string) => ["conversion", label] as const,
  unmatched: (label: string) => ["unmatched", label] as const,
  discarded: (label: string) => ["discarded", label] as const,
  run: (label: string) => ["run", label] as const,
  settings: ["settings"] as const,
  dats: ["dats"] as const,
  consoleKeys: ["console-keys"] as const,
};

export const useMeta = () =>
  useQuery({ queryKey: keys.meta, queryFn: () => api<Meta>("/meta"), staleTime: Infinity });
/** Every set; polled while one of them is scanning. */
export const useFolders = () =>
  useQuery({
    queryKey: keys.folders,
    queryFn: () => api<FolderCard[]>("/folders"),
    refetchInterval: (query) =>
      query.state.data?.some((f) => f.scan?.status === "running")
        ? (queryClient.getQueryData<Meta>(keys.meta)?.ui.poll_interval_ms ?? false)
        : false,
  });
export const useSettingsData = () =>
  useQuery({ queryKey: keys.settings, queryFn: () => api<SettingsData>("/settings") });
export const useDats = () =>
  useQuery({ queryKey: keys.dats, queryFn: () => api<DatRow[]>("/dats") });
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
    queryClient.invalidateQueries({ queryKey: keys.run(label) }),
    queryClient.invalidateQueries({ queryKey: keys.folders }),
  ]);
}
