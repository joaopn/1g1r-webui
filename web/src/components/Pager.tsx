import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Pager({
  page,
  pages,
  onPage,
}: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
}) {
  if (pages <= 1) return null;
  return (
    <nav className="flex items-center justify-center gap-2 text-sm" aria-label="Pages">
      <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        <ChevronLeft className="size-4" aria-hidden="true" /> Previous
      </Button>
      <span className="text-muted-foreground">
        Page {page} of {pages}
      </span>
      <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next <ChevronRight className="size-4" aria-hidden="true" />
      </Button>
    </nav>
  );
}
