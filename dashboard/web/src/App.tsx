import { useEffect, useState } from "react"
import { AppSidebar } from "@/components/AppSidebar"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { Lane } from "@/views/Lane"
import { Card } from "@/views/Card"
import { Appraise } from "@/views/Appraise"
import { SoldLog } from "@/views/SoldLog"
import { Calibration } from "@/views/Calibration"
import { Settings } from "@/views/Settings"
import { Toaster } from "@/components/ui/sonner"
import type { Mode, Vehicle, ViewName } from "@/lib/types"

const TITLES: Record<ViewName, string> = {
  lane: "The Lane", card: "Vehicle", appraise: "Appraise", sold: "Sold log",
  calib: "Calibration", settings: "Settings",
}

export default function App() {
  const [view, setView] = useState<ViewName>("lane")
  const [mode, setMode] = useState<Mode>("triage")
  const [profile, setProfile] = useState("charles")
  const [theme, setTheme] = useState<"dark" | "light">(() => (localStorage.getItem("am-theme") as any) || "dark")

  // lane state lifted here so Back / view-switches preserve the selected sale + cursor
  const [laneDate, setLaneDate] = useState<string>("")
  const [laneList, setLaneList] = useState<Vehicle[]>([])
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    localStorage.setItem("am-theme", theme)
  }, [theme])

  const current = laneList[idx]

  return (
    <SidebarProvider>
      <AppSidebar
        view={view} setView={setView} mode={mode} setMode={setMode}
        profile={profile} setProfile={setProfile}
        theme={theme} toggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-12 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
          <SidebarTrigger />
          <span className="font-heading text-sm font-medium text-muted-foreground">{TITLES[view]}</span>
          <span className="ml-auto font-mono text-[10px] text-muted-foreground/60" title="build marker — if this looks old after a refresh, your browser is caching">build {__BUILD_ID__}</span>
        </header>
        <main className="min-h-[calc(100svh-3rem)]">
          {view === "lane" && (
            <Lane profile={profile} date={laneDate} setDate={setLaneDate}
              onLoaded={setLaneList} onOpen={(i) => { setIdx(i); setView("card") }} />
          )}
          {view === "card" && (current
            ? <Card key={current.contract || idx} vehicle={current} mode={mode} profile={profile}
                onBack={() => setView("lane")}
                hasPrev={idx > 0} hasNext={idx < laneList.length - 1}
                onPrev={() => setIdx((i) => Math.max(0, i - 1))}
                onNext={() => setIdx((i) => Math.min(laneList.length - 1, i + 1))}
                position={laneList.length ? `${idx + 1} / ${laneList.length}` : undefined} />
            : <div className="p-10 text-sm text-muted-foreground">No vehicle selected.</div>)}
          {view === "appraise" && <Appraise mode={mode} profile={profile} />}
          {view === "sold" && <SoldLog />}
          {view === "calib" && <Calibration />}
          {view === "settings" && <Settings />}
        </main>
      </SidebarInset>
      <Toaster />
    </SidebarProvider>
  )
}
