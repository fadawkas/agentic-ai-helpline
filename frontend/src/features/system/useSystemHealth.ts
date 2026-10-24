import { useEffect, useState } from "react";
import { getReadiness } from "../../api/admin";
import type { Readiness } from "../../types/api";

export function useSystemHealth() {
  const [health, setHealth] = useState<Readiness | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let current = true;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await getReadiness();
        if (current) setHealth(result);
      } catch {
        if (current) setHealth(null);
      } finally {
        inFlight = false;
        if (current) setIsChecking(false);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { current = false; window.clearInterval(timer); };
  }, []);

  return { health, isChecking };
}
