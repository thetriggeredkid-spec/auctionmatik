import { Button } from "@/components/ui/button"

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground grid place-items-center gap-4">
      <h1 className="text-2xl font-semibold">Auctionmatik — shadcn migration</h1>
      <p className="text-muted-foreground text-sm">Toolchain online. Views porting next.</p>
      <Button>It works</Button>
    </div>
  )
}
