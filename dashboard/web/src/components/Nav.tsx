import { Button } from "@/components/ui/button"
import type { Mode, ViewName } from "@/lib/types"

const VIEWS: { id: ViewName; label: string }[] = [
  { id: "lane", label: "Lane" },
  { id: "appraise", label: "✦ Appraise" },
  { id: "sold", label: "Sold log" },
  { id: "calib", label: "Calibration" },
  { id: "settings", label: "Settings" },
]

export function Nav({
  view, setView, mode, setMode, profile, setProfile,
}: {
  view: ViewName
  setView: (v: ViewName) => void
  mode: Mode
  setMode: (m: Mode) => void
  profile: string
  setProfile: (p: string) => void
}) {
  return (
    <header className="sticky top-0 z-20 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4">
        <span className="font-heading text-lg font-semibold tracking-tight">Auctionmatik</span>
        <nav className="ml-4 flex items-center gap-1">
          {VIEWS.map((v) => (
            <Button
              key={v.id}
              size="sm"
              variant={view === v.id ? "secondary" : "ghost"}
              onClick={() => setView(v.id)}
            >
              {v.label}
            </Button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded-md border p-0.5">
            {(["triage", "deep"] as Mode[]).map((m) => (
              <Button key={m} size="sm" variant={mode === m ? "secondary" : "ghost"}
                className="h-7 px-2 text-xs" onClick={() => setMode(m)}>
                {m}
              </Button>
            ))}
          </div>
          <select
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="charles">charles</option>
            <option value="mechanic">mechanic</option>
          </select>
        </div>
      </div>
    </header>
  )
}
