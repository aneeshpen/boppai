// MagneticMascot — wraps the landing-page mascot so it gets gently pulled
// toward the cursor when the pointer comes near, then springs back to rest.
//
// The pull logic is adapted from the Originkit "Magnetic Hover Button": we
// measure the gap between the cursor and the element's edges, and once the
// cursor is within `reach` pixels we translate the mascot toward it with a
// falloff (further away = weaker pull), capped so it never wanders too far.
// framer-motion's useSpring gives the springy follow + settle-back feel.

import { motion, useMotionValue, useSpring } from 'framer-motion';
import { useRef, useEffect } from 'react';

const RANGE_PER_POINT = 18; // how many px of reach each "magnet" point buys
const MAX_PULL = 0.5;       // ceiling on how strongly we chase the cursor

export default function MagneticMascot({
  children,
  className = '',
  magnet = 12, // strength/reach dial — higher = pulls from further, harder
}) {
  const ref = useRef(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 260, damping: 18, mass: 0.4 });
  const sy = useSpring(y, { stiffness: 260, damping: 18, mass: 0.4 });

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const pull = (magnet / 20) * MAX_PULL;
    const reach = magnet * RANGE_PER_POINT;

    function onMove(event) {
      const rect = node.getBoundingClientRect();
      // Subtract the current spring offset so we measure against the resting
      // center, not the already-nudged position (prevents runaway drift).
      const cx = rect.left + rect.width / 2 - sx.get();
      const cy = rect.top + rect.height / 2 - sy.get();

      const dx = event.clientX - cx;
      const dy = event.clientY - cy;

      const edgeX = Math.max(0, Math.abs(dx) - rect.width / 2);
      const edgeY = Math.max(0, Math.abs(dy) - rect.height / 2);
      const gap = Math.hypot(edgeX, edgeY);

      if (gap > reach) {
        x.set(0);
        y.set(0);
        return;
      }
      const falloff = reach === 0 ? 0 : 1 - gap / reach;
      x.set(dx * pull * falloff);
      y.set(dy * pull * falloff);
    }

    function onLeave() {
      x.set(0);
      y.set(0);
    }

    window.addEventListener('pointermove', onMove);
    document.addEventListener('pointerleave', onLeave);
    return () => {
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerleave', onLeave);
    };
  }, [magnet, x, y, sx, sy]);

  return (
    <motion.div ref={ref} className={className} style={{ x: sx, y: sy }}>
      {children}
    </motion.div>
  );
}
