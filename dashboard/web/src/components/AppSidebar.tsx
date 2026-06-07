import { LayoutGrid, Sparkles, NotebookPen, Target, Settings as SettingsIcon, Sun, Moon } from "lucide-react"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarHeader,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import type { Mode, ViewName } from "@/lib/types"

const NAV: { id: ViewName; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "lane", label: "Lane", icon: LayoutGrid },
  { id: "appraise", label: "Appraise", icon: Sparkles },
  { id: "sold", label: "Sold log", icon: NotebookPen },
  { id: "calib", label: "Calibration", icon: Target },
  { id: "settings", label: "Settings", icon: SettingsIcon },
]

export function AppSidebar({
  view, setView, mode, setMode, profile, setProfile, theme, toggleTheme,
}: {
  view: ViewName; setView: (v: ViewName) => void
  mode: Mode; setMode: (m: Mode) => void
  profile: string; setProfile: (p: string) => void
  theme: "dark" | "light"; toggleTheme: () => void
}) {
  return (
    <Sidebar collapsible="icon" variant="floating">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-1 py-1.5">
          <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary text-primary-foreground font-heading text-sm font-bold">A</div>
          <span className="font-heading text-base font-semibold tracking-tight group-data-[collapsible=icon]:hidden">Auctionmatik</span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu>
            {NAV.map((n) => (
              <SidebarMenuItem key={n.id}>
                <SidebarMenuButton isActive={view === n.id} tooltip={n.label} onClick={() => setView(n.id)}>
                  <n.icon className="size-4" />
                  <span>{n.label}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="space-y-2 group-data-[collapsible=icon]:hidden">
          <div>
            <SidebarGroupLabel className="px-0">Mode</SidebarGroupLabel>
            <ToggleGroup variant="outline" size="sm" value={[mode]}
              onValueChange={(v) => v[0] && setMode(v[0] as Mode)} className="w-full">
              <ToggleGroupItem value="triage" className="flex-1 text-xs">triage</ToggleGroupItem>
              <ToggleGroupItem value="deep" className="flex-1 text-xs">deep</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div>
            <SidebarGroupLabel className="px-0">Profile</SidebarGroupLabel>
            <Select value={profile} onValueChange={(v) => v && setProfile(v)}>
              <SelectTrigger size="sm" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="charles">charles</SelectItem>
                <SelectItem value="mechanic">mechanic</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" size="sm" className="w-full justify-start gap-2" onClick={toggleTheme}>
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            {theme === "dark" ? "Light" : "Dark"} mode
          </Button>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
