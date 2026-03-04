import { useEffect } from "react";
import { useRouter } from "next/router";

export default function CombinedPvaluesRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/most-significant");
  }, [router]);
  return null;
}
