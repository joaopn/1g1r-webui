import type { LucideIcon } from "lucide-react";
import {
  ChartColumn,
  ChevronLeft,
  ChevronRight,
  Gamepad2,
  House,
  Menu,
  Plus,
  Settings as SettingsIcon,
} from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import logo from "@/assets/logo.svg";
import { AddPlatformDialog } from "@/components/AddPlatformDialog";
import { AddRomsetsDialog } from "@/components/AddRomsetsDialog";
import { AddSetsDialog } from "@/components/AddSetsDialog";
import { Notifications } from "@/components/layout/Notifications";
import { PlatformIcon } from "@/components/PlatformIcon";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Tour } from "@/components/Tour";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { foldersByName } from "@/lib/platforms";
import { useFolders, useMeta } from "@/lib/queries";
import { folderState, openingSection, sectionPath } from "@/lib/sections";
import { isBoolean, isNumber, isStringArray, readJson, removeKey, writeJson } from "@/lib/storage";
import type { FolderCard, Meta } from "@/lib/types";
import { clampRem, useDragWidth } from "@/lib/useDragWidth";
import { cn } from "@/lib/utils";

/** Groups somebody opened by hand stay open across visits; every group starts closed. */
const OPEN_GROUPS_KEY = "g1r.sidebar.groups.v1";
const WIDTH_KEY = "g1r.sidebar.width.v1";
const COLLAPSED_KEY = "g1r.sidebar.collapsed.v1";

/**
 * `prefix`: the paths the entry stands for (a set's every tab), when wider than `to`.
 * `tour`: the first-run tour's name for it.
 */
type NavChild = { to: string; label: ReactNode; title: string; prefix?: string; tour?: string };
type NavGroupItem = { id: string; label: string; icon: LucideIcon; children: NavChild[] };

const childPrefix = (child: NavChild) => child.prefix ?? child.to;

function folderChildren(folders: FolderCard[], meta: Meta | undefined): NavChild[] {
  return foldersByName(folders, meta?.platforms).map((folder) => {
    const platform = meta?.platforms[folder.platform];
    return {
      to: sectionPath(folder.label, openingSection(folder)),
      prefix: `/folders/${folder.label}/`,
      title: `${platform?.name ?? folder.platform} · ${folder.label}`,
      label: (
        <span className="flex min-w-0 items-center gap-2">
          <PlatformIcon
            platform={platform}
            state={folderState(folder)}
            widthRem={meta?.ui.platform_icon_width_rem}
          />
          <span className="truncate">{platform?.name ?? folder.platform}</span>
          <span className="shrink-0 text-muted-foreground text-xs">{folder.label}</span>
        </span>
      ),
    };
  });
}

export function navGroups(folders: FolderCard[], meta: Meta | undefined): NavGroupItem[] {
  return [
    { id: "romsets", label: "Romsets", icon: Gamepad2, children: folderChildren(folders, meta) },
    {
      id: "settings",
      label: "Settings",
      icon: SettingsIcon,
      children: [
        { to: "/settings/dat-sources", label: "Which DATs to use?", title: "Which DATs to use?" },
        { to: "/settings/romsets", label: "Romset management", title: "Romset management" },
        {
          to: "/settings/dats",
          label: "Platform DATs",
          title: "Platform DATs",
          tour: "platform-dats",
        },
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

function NavGroup({
  group,
  onNavigate,
  reveal,
}: {
  group: NavGroupItem;
  onNavigate?: () => void;
  /** Opened for the first-run tour, which points at one of its entries. */
  reveal?: boolean;
}) {
  const { pathname } = useLocation();
  const inside = group.children.some((child) => pathname.startsWith(childPrefix(child)));
  const [open, setOpen] = useState(
    () => inside || readJson(OPEN_GROUPS_KEY, [], isStringArray).includes(group.id),
  );
  const listId = useId();
  const Icon = group.icon;

  // The page you are on is never folded out of sight.
  useEffect(() => {
    if (inside || reveal) setOpen(true);
  }, [inside, reveal]);

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
          <li className="px-2.5 py-1.5 text-muted-foreground text-xs">No romsets yet</li>
        ) : (
          group.children.map((child) => (
            <li key={child.to}>
              <NavLink
                to={child.to}
                title={child.title}
                onClick={onNavigate}
                data-tour={child.tour}
                className={cn(rowClass(pathname.startsWith(childPrefix(child))), "py-1.5")}
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

function NavItems({ onNavigate, reveal }: { onNavigate?: () => void; reveal?: string | null }) {
  const meta = useMeta();
  const folders = useFolders();
  // Hidden sets stay out of the sidebar (Settings → Romset management lists them).
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
      <NavLink
        to="/statistics"
        onClick={onNavigate}
        className={({ isActive }) => rowClass(isActive)}
      >
        <ChartColumn className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1">Statistics</span>
      </NavLink>
      {groups.map((group) => (
        <NavGroup
          key={group.id}
          group={group}
          onNavigate={onNavigate}
          reveal={group.id === reveal}
        />
      ))}
    </nav>
  );
}

type Adding = "choose" | "one" | "many" | null;

function SidebarFoot({ onAdd }: { onAdd: () => void }) {
  const meta = useMeta();
  const source = meta.data?.app.source_url;
  return (
    <div className="mt-auto flex flex-col gap-3 pt-4">
      <Button
        onClick={onAdd}
        className="justify-center gap-2"
        data-testid="add-romsets"
        data-tour="add-romsets"
      >
        <Plus className="size-4" aria-hidden="true" />
        Add romsets
      </Button>
      <p className="text-center text-muted-foreground text-xs" data-testid="license">
        License: AGPL 3.0 ·{" "}
        {source ? (
          <a className="underline" href={source}>
            Source code
          </a>
        ) : (
          <span className="text-status-warn">Source URL not configured</span>
        )}
      </p>
    </div>
  );
}

/** The app's mark, drawn in the theme's primary colour through the favicon's shape. */
function Logo() {
  return (
    <span
      aria-hidden="true"
      data-testid="logo"
      className="size-5 shrink-0 bg-primary [mask-repeat:no-repeat] [mask-size:contain]"
      style={{ maskImage: `url(${logo})` }}
    />
  );
}

/** The round button sitting on the sidebar's edge line, near its top. */
function CollapseButton({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const label = collapsed ? "Expand the sidebar" : "Collapse the sidebar";
  const Icon = collapsed ? ChevronRight : ChevronLeft;
  return (
    <button
      type="button"
      aria-label={label}
      aria-expanded={!collapsed}
      title={label}
      data-testid="sidebar-collapse"
      onClick={onToggle}
      className={cn(
        "-right-3 absolute top-5 z-20 flex size-6 items-center justify-center rounded-full",
        "border border-border bg-background text-muted-foreground shadow-sm transition-colors",
        "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
    </button>
  );
}

/** The frame every page renders in: a resizable sidebar on desktop, a sheet on narrow screens. */
export function AppShell() {
  const meta = useMeta();
  const bounds = meta.data?.ui.sidebar;
  const [mobileOpen, setMobileOpen] = useState(false);
  const [adding, setAdding] = useState<Adding>(null);
  const [collapsed, setCollapsed] = useState(() => readJson(COLLAPSED_KEY, false, isBoolean));
  const toggleCollapsed = () => {
    setCollapsed(!collapsed);
    writeJson(COLLAPSED_KEY, !collapsed);
  };
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
  const [revealGroup, setRevealGroup] = useState<string | null>(null);
  // The tour's target sits in the sidebar: open its group, then show the sidebar (expanded for
  // this visit, not saved) or, at phone width, the menu sheet.
  const reveal = (group?: string) => {
    if (group) setRevealGroup(group);
    const shown = (id: string) =>
      (document.querySelector(`[data-testid="${id}"]`)?.getClientRects().length ?? 0) > 0;
    if (shown("sidebar")) return;
    if (shown("sidebar-collapsed")) setCollapsed(false);
    else setMobileOpen(true);
  };

  return (
    <div className="flex min-h-screen bg-background">
      {collapsed ? (
        <aside
          data-testid="sidebar-collapsed"
          aria-label="Sidebar (collapsed)"
          className="sticky top-0 z-30 hidden h-screen w-3 shrink-0 border-border border-r bg-sidebar md:block"
        >
          <CollapseButton collapsed onToggle={toggleCollapsed} />
        </aside>
      ) : null}
      <aside
        data-testid="sidebar"
        style={width === null ? undefined : { width: `${width}rem` }}
        className={cn(
          "sticky top-0 z-30 hidden h-screen shrink-0 flex-col border-border border-r bg-sidebar px-3 py-4",
          !collapsed && "md:flex",
        )}
      >
        <CollapseButton collapsed={false} onToggle={toggleCollapsed} />
        <div className="flex items-center gap-2 pb-4 pl-2.5">
          <Logo />
          <span className="min-w-0 flex-1 truncate font-semibold text-sidebar-foreground tracking-tight">
            {name}
          </span>
          <div className="flex items-center gap-0.5">
            <ThemeToggle />
            <Notifications />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <NavItems reveal={revealGroup} />
        </div>
        <SidebarFoot onAdd={() => setAdding("choose")} />
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
              <SheetHeader className="flex-row items-center p-0 pr-8 pb-4">
                <SheetTitle className="flex-1">{name}</SheetTitle>
                <ThemeToggle />
                <Notifications />
              </SheetHeader>
              <NavItems onNavigate={() => setMobileOpen(false)} reveal={revealGroup} />
              <SidebarFoot
                onAdd={() => {
                  setMobileOpen(false);
                  setAdding("choose");
                }}
              />
            </SheetContent>
          </Sheet>
          <Logo />
          <span className="font-medium text-sm">{name}</span>
        </header>
        <main className="w-full flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
      <Tour reveal={reveal} />
      <AddRomsetsDialog
        open={adding === "choose"}
        onOpenChange={(open) => setAdding(open ? "choose" : null)}
        onChoose={setAdding}
      />
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
