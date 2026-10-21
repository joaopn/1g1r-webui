import { FolderPlus, FolderTree } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** "Add romsets": the choice between the two ways to add sets, each opening its own dialog. */
export function AddRomsetsDialog({
  open,
  onOpenChange,
  onChoose,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (what: "one" | "many") => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add romsets</DialogTitle>
          <DialogDescription>
            Automatch a folder holding one folder per platform, or add one platform folder.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Button onClick={() => onChoose("many")} className="justify-center gap-2">
            <FolderTree className="size-4" aria-hidden="true" />
            Automatch folders
          </Button>
          <Button
            variant="outline"
            onClick={() => onChoose("one")}
            className="justify-center gap-2"
          >
            <FolderPlus className="size-4" aria-hidden="true" />
            Add single folder
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
