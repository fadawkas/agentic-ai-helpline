import { useEffect, useState } from "react";
import { getSession } from "../../api/admin";

export function useAdminSession() {
  const [username, setUsername] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let current = true;
    void getSession().then((session) => {
      if (current) setUsername(session?.username ?? null);
    }).catch(() => {
      if (current) setUsername(null);
    }).finally(() => {
      if (current) setIsChecking(false);
    });
    return () => { current = false; };
  }, []);

  return { username, setUsername, isChecking };
}
