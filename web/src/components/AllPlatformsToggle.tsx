/** Lists of platforms show only those with a set unless this is ticked. */
export function AllPlatformsToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="size-3.5 accent-primary"
        checked={checked}
        onChange={() => onChange(!checked)}
      />
      All platforms <span className="text-muted-foreground">(else only those with a set)</span>
    </label>
  );
}
