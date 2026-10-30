import { useEffect, useLayoutEffect, useRef } from 'react';
import { createRelayMascot, type MascotController, type MascotShape } from '../mascot/engine.js';
import '../mascot/mascot.css';

export interface RelayMascotProps {
  size?: number;
  emotionId?: string;
  shape?: MascotShape;
  animated?: boolean;
  /** Omit beside visible Relay/status text to avoid redundant screen-reader output. */
  label?: string;
}

export default function RelayMascot({ size = 24, emotionId = 'idle', shape = 'blob', animated = false, label }: RelayMascotProps) {
  const host = useRef<HTMLSpanElement>(null);
  const controller = useRef<MascotController | null>(null);
  useLayoutEffect(() => {
    const instance = createRelayMascot(host.current!, { animated: false });
    controller.current = instance;
    return () => { instance.destroy(); controller.current = null; };
  }, []);
  useEffect(() => { controller.current?.setEmotion(emotionId); }, [emotionId]);
  useEffect(() => { controller.current?.setShape(shape); }, [shape]);
  useEffect(() => { controller.current?.setAnimated(animated); }, [animated]);
  return <span ref={host} className="relay-mark" style={{ width: size, height: size }} data-compact={size < 28}
    role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} />;
}
