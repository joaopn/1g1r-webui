import type { LucideIcon } from "lucide-react";
import {
  Archive,
  ChevronRight,
  FileCog,
  FolderTree,
  House,
  ListChecks,
  Menu,
  Plus,
  Settings as SettingsIcon,
} from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { AddPlatformDialog } from "@/components/AddPlatformDialog";
import { AddSetsDialog } from "@/components/AddSetsDialog";
import { PlatformIcon } from "@/components/PlatformIcon";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { foldersByName } from "@/lib/platforms";
import { useFolders, useMeta } from "@/lib/queries";
import { isNumber, isStringArray, readJson, removeKey, writeJson } from "@/lib/storage";
import type { FolderCard, Meta } from "@/lib/types";
import { clampRem, useDragWidth } from "@/lib/useDragWidth";
import { cn } from "@/lib/utils";

/** Groups somebody opened by hand stay open across visits; every group starts closed. */
const OPEN_GROUPS_KEY = "g1r.sidebar.groups.v1";
const WIDTH_KEY = "g1r.sidebar.width.v1";

type NavChild = { to: string; label: ReactNode; title: string };
type NavGroupItem = { id: string; label: string; icon: LucideIcon; children: NavChild[] };

function folderChildren(
  folders: FolderCard[],
  meta: Meta | undefined,
  section: string,
): NavChild[] {
  return foldersByName(folders, meta?.platforms).map((folder) => {
    const platform = meta?.platforms[folder.platform];
    return {
      to: `/folders/${folder.label}/${section}`,
      title: `${platform?.name ?? folder.platform} · ${folder.label}`,
      label: (
        <span className="flex min-w-0 items-center gap-2">
          <PlatformIcon platform={platform} widthRem={meta?.ui.platform_icon_width_rem} />
          <span className="truncate">{platform?.name ?? folder.platform}</span>
          <span className="shrink-0 text-muted-foreground text-xs">{folder.label}</span>
        </span>
      ),
    };
  });
}

export function navGroups(folders: FolderCard[], meta: Meta | undefined): NavGroupItem[] {
  return [
    {
      id: "conversion",
      label: "Conversion",
      icon: FileCog,
      children: folderChildren(folders, meta, "conversion"),
    },
    {
      id: "matching",
      label: "Matching & 1G1R",
      icon: ListChecks,
      children: folderChildren(folders, meta, "matching"),
    },
    {
      id: "discarded",
      label: "Discarded",
      icon: Archive,
      children: folderChildren(folders, meta, "discarded"),
    },
    {
      id: "settings",
      label: "Settings",
      icon: SettingsIcon,
      children: [
        { to: "/settings/dat-sources", label: "Which DATs to use?", title: "Which DATs to use?" },
        { to: "/settings/sets", label: "Sets", title: "Sets" },
        { to: "/settings/platforms", label: "Platforms & files", title: "Platforms & files" },
        { to: "/settings/dats", label: "Platform DATs", title: "Platform DATs" },
        { to: "/settings/lookups", label: "Online lookups", title: "Online lookups" },
        { to: "/settings/advanced", label: "Advanced", title: "Advanced" },
      ],
    },
  ];
}

function rowClass(active: boolean) {
  return cn(
    "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
    active
      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
      : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
  );
}

function NavGroup({ group, onNavigate }: { group: NavGroupItem; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const inside = group.children.some((child) => pathname.startsWith(child.to));
  const [open, setOpen] = useState(
    () => inside || readJson(OPEN_GROUPS_KEY, [], isStringArray).includes(group.id),
  );
  const listId = useId();
  const Icon = group.icon;

  // The page you are on is never folded out of sight.
  useEffect(() => {
    if (inside) setOpen(true);
  }, [inside]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    const others = readJson(OPEN_GROUPS_KEY, [], isStringArray).filter((id) => id !== group.id);
    writeJson(OPEN_GROUPS_KEY, next ? [...others, group.id] : others);
  };

  return (
    <div className="flex flex-col gap-0.5">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={toggle}
        className={cn(rowClass(false), "text-left", inside && "text-sidebar-foreground")}
      >
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 truncate">{group.label}</span>
        <ChevronRight
          aria-hidden="true"
          data-testid={`chevron-${group.id}`}
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
            open && "rotate-90",
          )}
        />
      </button>
      <ul
        id={listId}
        hidden={!open}
        aria-label={group.label}
        className={cn("ml-4 flex flex-col gap-0.5 border-border border-l pl-2", !open && "hidden")}
      >
        {group.children.length === 0 ? (
          <li className="px-2.5 py-1.5 text-muted-foreground text-xs">No platforms yet</li>
        ) : (
          group.children.map((child) => (
            <li key={child.to}>
              <NavLink
                to={child.to}
                title={child.title}
                onClick={onNavigate}
                className={({ isActive }) => cn(rowClass(isActive), "py-1.5")}
              >
                {child.label}
              </NavLink>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const meta = useMeta();
  const folders = useFolders();
  // Hidden sets stay out of the sidebar (Settings → Sets lists them).
  const groups = navGroups(
    (folders.data ?? []).filter((f) => !f.hidden),
    meta.data,
  );
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      <NavLink to="/" end onClick={onNavigate} className={({ isActive }) => rowClass(isActive)}>
        <House className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1">Home</span>
      </NavLink>
      {groups.map((group) => (
        <NavGroup key={group.id} group={group} onNavigate={onNavigate} />
      ))}
    </nav>
  );
}

type Adding = "one" | "many" | null;

function SidebarFoot({ onAdd }: { onAdd: (what: Exclude<Adding, null>) => void }) {
  return (
    <div className="mt-auto flex flex-col gap-1 pt-4">
      <Button onClick={() => onAdd("one")} className="justify-center gap-2" data-testid="add-set">
        <Plus className="size-4" aria-hidden="true" />
        Add set
      </Button>
      <Button
        variant="outline"
        onClick={() => onAdd("many")}
        className="justify-center gap-2"
        data-testid="add-sets"
      >
        <FolderTree className="size-4" aria-hidden="true" />
        Add sets from a folder
      </Button>
      <ThemeToggle />
    </div>
  );
}

/** The frame every page renders in: a resizable sidebar on desktop, a sheet on narrow screens. */
export function AppShell() {
  const meta = useMeta();
  const bounds = meta.data?.ui.sidebar;
  const [mobileOpen, setMobileOpen] = useState(false);
  const [adding, setAdding] = useState<Adding>(null);
  const [stored, setStored] = useState<number | null>(() => {
    const value = readJson<number | null>(WIDTH_KEY, null, (v): v is number => isNumber(v));
    return value;
  });
  const width = bounds
    ? stored === null
      ? bounds.width_rem
      : clampRem(stored, bounds.min_rem, bounds.max_rem)
    : null;
  const drag = useDragWidth({
    width: width ?? 0,
    min: bounds?.min_rem ?? 0,
    max: bounds?.max_rem ?? 0,
    step: meta.data?.ui.resize_step_rem ?? 0,
    shiftMultiplier: meta.data?.ui.resize_shift_multiplier ?? 1,
    defaultPx: meta.data?.ui.rem_fallback_px ?? 1,
    onChange: (rem) => {
      setStored(rem);
      writeJson(WIDTH_KEY, rem);
    },
    onReset: () => {
      setStored(null);
      removeKey(WIDTH_KEY);
    },
  });
  const name = meta.data?.app.name ?? "1g1r-webui";

  return (
    <div className="flex min-h-screen bg-background">
      <aside
        data-testid="sidebar"
        style={width === null ? undefined : { width: `${width}rem` }}
        className="sticky top-0 hidden h-screen shrink-0 flex-col border-border border-r bg-sidebar px-3 py-4 md:flex"
      >
        <div className="px-2.5 pb-4">
          <span className="font-semibold text-sidebar-foreground tracking-tight">{name}</span>
          <p className="text-muted-foreground text-xs">one game, one ROM</p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <NavItems />
        </div>
        <SidebarFoot onAdd={setAdding} />
        {bounds ? (
          // biome-ignore lint/a11y/useSemanticElements: an <hr> cannot take focus or a value; a focusable separator is the ARIA splitter.
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the sidebar"
            aria-valuenow={width ?? undefined}
            aria-valuemin={bounds.min_rem}
            aria-valuemax={bounds.max_rem}
            tabIndex={0}
            title="Drag to resize, double-click to reset"
            data-testid="sidebar-resize"
            className={cn(
              "-right-1.5 absolute top-0 z-10 flex h-full w-3 cursor-col-resize touch-none select-none justify-center",
              "after:h-full after:w-px after:bg-transparent hover:after:bg-foreground/30",
              "focus-visible:outline-none focus-visible:after:w-0.5 focus-visible:after:bg-ring",
            )}
            {...drag}
          />
        ) : null}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-2 border-border border-b bg-background/95 px-4 py-2.5 backdrop-blur md:hidden">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open navigation">
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="flex w-72 flex-col p-4">
              <SheetHeader className="p-0 pb-4">
                <SheetTitle>{name}</SheetTitle>
              </SheetHeader>
              <NavItems onNavigate={() => setMobileOpen(false)} />
              <SidebarFoot
                onAdd={(what) => {
                  setMobileOpen(false);
                  setAdding(what);
                }}
              />
            </SheetContent>
          </Sheet>
          <span className="font-medium text-sm">{name}</span>
        </header>
        <main className="w-full flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
        <footer className="border-border border-t px-4 py-2 text-muted-foreground text-xs md:px-8">
          {name} · AGPL-3.0-or-later ·{" "}
          {meta.data?.app.source_url ? (
            <a className="underline" href={meta.data.app.source_url}>
              Source code
            </a>
          ) : (
            <span className="text-status-warn">Source URL not configured</span>
          )}
        </footer>
      </div>
      <AddPlatformDialog
        open={adding === "one"}
        onOpenChange={(open) => setAdding(open ? "one" : null)}
      />
      <AddSetsDialog
        open={adding === "many"}
        onOpenChange={(open) => setAdding(open ? "many" : null)}
      />
    </div>
  );
}
