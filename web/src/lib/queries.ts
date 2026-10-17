import { QueryClient, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  Conversion,
  DatRow,
  Discarded,
  FolderCard,
  FolderDetail,
  Game,
  Meta,
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
  settings: ["settings"] as const,
  dats: ["dats"] as const,
};

export const useMeta = () =>
  useQuery({ queryKey: keys.meta, queryFn: () => api<Meta>("/meta"), staleTime: Infinity });
export const useFolders = () =>
  useQuery({ queryKey: keys.folders, queryFn: () => api<FolderCard[]>("/folders") });
export const useSettingsData = () =>
  useQuery({ queryKey: keys.settings, queryFn: () => api<SettingsData>("/settings") });
export const useDats = () =>
  useQuery({ queryKey: keys.dats, queryFn: () => api<DatRow[]>("/dats") });
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
    queryClient.invalidateQueries({ queryKey: keys.folders }),
  ]);
}
