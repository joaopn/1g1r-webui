import { Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { readTheme, saveTheme, type ThemeChoice } from "@/lib/theme";

const NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const ICON = { system: Monitor, light: Sun, dark: Moon };

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);
  const Icon = ICON[choice];
  return (
    <Button
      variant="ghost"
      size="sm"
      className="justify-start gap-2"
      onClick={() => {
        const next = NEXT[choice];
        saveTheme(next);
        setChoice(next);
      }}
      title={`Theme: ${choice} (click to change)`}
    >
      <Icon className="size-4" aria-hidden="true" />
      {compact ? <span className="sr-only">Theme: {choice}</span> : <span>Theme: {choice}</span>}
    </Button>
  );
}
