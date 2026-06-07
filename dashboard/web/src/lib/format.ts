// Money + misc formatters (dollars in; the API stores cents but the design vehicle is dollars).

export function fmt(dollars: number | null | undefined): string {
  if (dollars == null || Number.isNaN(dollars)) return "—"
  return "$" + Math.round(dollars).toLocaleString()
}

export function km(n: number | null | undefined): string {
  if (!n) return "—"
  return n.toLocaleString() + " km"
}

// Route external comp images (esp. Facebook CDN, which 403s on hotlink) through the
// server-side proxy so they render. Regal CloudFront loads fine direct, so leave it.
export function img(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  if (url.includes("cloudfront.net") || url.startsWith("/")) return url
  return "/api/img?u=" + encodeURIComponent(url)
}

export const VERDICT_LABEL: Record<string, string> = {
  BID: "BID",
  BID_TO_FIX: "BID-TO-FIX",
  PASS: "PASS",
}

// shadcn badge variant per verdict
export function verdictVariant(v: string | null | undefined): "default" | "secondary" | "destructive" | "outline" {
  if (v === "BID") return "default"
  if (v === "BID_TO_FIX") return "secondary"
  if (v === "PASS") return "destructive"
  return "outline"
}
