import { useEffect, useRef, useState } from "react";

/**
 * Animates a number from its previous value to `target` using an ease-out cubic.
 * Respects prefers-reduced-motion — snaps immediately if reduced motion is set.
 */
export function useCountUp(target: number, duration = 700, decimals = 0): number {
  const [value, setValue] = useState(target);
  const prev = useRef(target);
  const raf = useRef<number>(0);

  useEffect(() => {
    if (typeof window !== "undefined" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(target);
      prev.current = target;
      return;
    }

    const start = prev.current;
    const diff = target - start;
    const startTime = performance.now();

    function tick(now: number) {
      const t = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // cubic ease-out
      setValue(parseFloat((start + diff * eased).toFixed(decimals)));
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else prev.current = target;
    }

    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration, decimals]);

  return value;
}
