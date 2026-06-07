import { useState } from "react"
import { Nav } from "@/components/Nav"
import { Lane } from "@/views/Lane"
import { Card } from "@/views/Card"
import { Toaster } from "@/components/ui/sonner"
import type { Mode, Vehicle, ViewName } from "@/lib/types"

function Placeholder({ title }: { title: string }) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-16 text-center text-muted-foreground">
      <h1 className="font-heading text-2xl font-semibold text-foreground">{title}</h1>
      <p className="mt-2 text-sm">Porting to shadcn — coming in the next step.</p>
    </div>
  )
}

export default function App() {
  const [view, setView] = useState<ViewName>("lane")
  const [mode, setMode] = useState<Mode>("triage")
  const [profile, setProfile] = useState("charles")
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)

  function open(v: Vehicle) {
    setVehicle(v)
    setView("card")
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Nav view={view} setView={setView} mode={mode} setMode={setMode} profile={profile} setProfile={setProfile} />
      {view === "lane" && <Lane profile={profile} onOpen={open} />}
      {view === "card" && (vehicle
        ? <Card vehicle={vehicle} mode={mode} profile={profile} onBack={() => setView("lane")} />
        : <Placeholder title="No vehicle selected" />)}
      {view === "appraise" && <Placeholder title="✦ Appraise" />}
      {view === "sold" && <Placeholder title="Sold log" />}
      {view === "calib" && <Placeholder title="Calibration" />}
      {view === "settings" && <Placeholder title="Settings" />}
      <Toaster />
    </div>
  )
}
