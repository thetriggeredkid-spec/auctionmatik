import { useEffect, useState } from "react"
import { Nav } from "@/components/Nav"
import { Lane } from "@/views/Lane"
import { Card } from "@/views/Card"
import { Appraise } from "@/views/Appraise"
import { SoldLog } from "@/views/SoldLog"
import { Calibration } from "@/views/Calibration"
import { Settings } from "@/views/Settings"
import { Toaster } from "@/components/ui/sonner"
import type { Mode, Vehicle, ViewName } from "@/lib/types"

export default function App() {
  const [view, setView] = useState<ViewName>("lane")
  const [mode, setMode] = useState<Mode>("triage")
  const [profile, setProfile] = useState("charles")
  const [theme, setTheme] = useState<"dark" | "light">(() => (localStorage.getItem("am-theme") as any) || "dark")

  // lane list + cursor so the card can page prev/next through the sale
  const [laneList, setLaneList] = useState<Vehicle[]>([])
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    localStorage.setItem("am-theme", theme)
  }, [theme])

  const current = laneList[idx]

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Nav
        view={view} setView={setView} mode={mode} setMode={setMode}
        profile={profile} setProfile={setProfile}
        theme={theme} toggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      />
      {view === "lane" && (
        <Lane profile={profile}
          onLoaded={setLaneList}
          onOpen={(i) => { setIdx(i); setView("card") }} />
      )}
      {view === "card" && current && (
        <Card
          key={current.contract || idx}
          vehicle={current}
          mode={mode} profile={profile}
          onBack={() => setView("lane")}
          hasPrev={idx > 0} hasNext={idx < laneList.length - 1}
          onPrev={() => setIdx((i) => Math.max(0, i - 1))}
          onNext={() => setIdx((i) => Math.min(laneList.length - 1, i + 1))}
          position={laneList.length ? `${idx + 1} / ${laneList.length}` : undefined}
        />
      )}
      {view === "appraise" && <Appraise mode={mode} profile={profile} />}
      {view === "sold" && <SoldLog />}
      {view === "calib" && <Calibration />}
      {view === "settings" && <Settings />}
      <Toaster />
    </div>
  )
}
