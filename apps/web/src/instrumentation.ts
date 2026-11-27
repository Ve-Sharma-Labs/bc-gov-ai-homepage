import { jurisdiction } from "@/lib/jurisdiction";

export function register() {
  const requested = process.env.JURISDICTION ?? "bc";
  if (process.env.NEXT_RUNTIME === "nodejs" && process.env.NODE_ENV === "production"
    && requested !== jurisdiction.id) {
    console.error(`Web build jurisdiction ${jurisdiction.id} does not match runtime JURISDICTION ${requested}. Rebuild the selected pack.`);
    process.exit(1);
  }
}
