import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { PICTURE_DRAW_MS, usePictureLoads } from "./pictureProbe";

/**
 * A picture never stops a render (pictureProbe.ts says why). Every picture the renderer draws goes through
 * SafeImg instead of remotion's <Img>:
 *
 *   - it is loaded once first (pictureProbe: a load that always settles), and only one that loaded reaches
 *     an <Img>, from the browser's cache by then;
 *   - an <Img> that fails anyway, or has not drawn after PICTURE_DRAW_MS, is taken down (which lets go of the
 *     frame's hold) and the fallback is drawn instead;
 *   - the fallback: `fallback` when given, else `fallbackStill` blurred (BlurredHold), else nothing.
 *
 * A scene's picture falls back to the shot before it, blurred (media.fallbackStill, set by the check before
 * the render in src/quality.py, else the neighbour the document gives it): never a blank frame.
 */

type ImgProps = React.ComponentProps<typeof Img>;

export type SafeImgProps = ImgProps & {
  /** Drawn instead when the picture cannot be drawn (null: nothing). */
  fallback?: React.ReactNode;
  /** Without `fallback`: this picture (the first of these that can be drawn), blurred and dimmed, instead. */
  fallbackStill?: string | string[];
  /** Told once the picture is given up (it did not load, failed to draw, or took too long). */
  onFail?: () => void;
};

/** The dark, softly lit field under a held picture: what shows when none at all can be drawn. */
export const HOLD_FIELD = "radial-gradient(ellipse at 45% 42%, #23262d 0%, #121418 62%, #0a0b0e 100%)";

const SafeImgOnce: React.FC<SafeImgProps> = ({ src, fallback, fallbackStill, onFail, onError, onImageFrame, ...rest }) => {
  const loads = usePictureLoads(src || undefined);
  const [failed, setFailed] = React.useState(false);
  const [drawn, setDrawn] = React.useState(false);
  const failRef = React.useRef(onFail);
  failRef.current = onFail;
  const frameRef = React.useRef(onImageFrame);
  frameRef.current = onImageFrame;
  const told = React.useRef(false);
  const giveUp = React.useCallback(() => {
    setFailed(true);
    if (!told.current) {
      told.current = true;
      failRef.current?.();
    }
  }, []);
  React.useEffect(() => {
    if (loads === false) giveUp();
  }, [loads, giveUp]);
  React.useEffect(() => {
    // Loaded once already, so it draws from the cache: one still not drawn by now is let go.
    if (loads !== true || drawn || failed) return;
    const t = setTimeout(giveUp, PICTURE_DRAW_MS);
    return () => clearTimeout(t);
  }, [loads, drawn, failed, giveUp]);
  // Stable: remotion's <Img> loads its picture again whenever this changes.
  const onFrame = React.useCallback((el: HTMLImageElement) => {
    setDrawn(true);
    frameRef.current?.(el);
  }, []);
  if (loads === null) return null;                      // (the frame waits for the load: it always settles)
  if (loads === false || failed) {
    if (fallback !== undefined) return <>{fallback}</>;
    return fallbackStill ? <BlurredHold still={fallbackStill} /> : null;
  }
  return (
    <Img src={src} {...rest} onImageFrame={onFrame}
      onError={(e) => {
        onError?.(e);
        giveUp();
      }} />
  );
};

/** remotion's <Img>, except that its picture never fails or holds up the render. */
export const SafeImg: React.FC<SafeImgProps> = (props) => <SafeImgOnce key={String(props.src || "")} {...props} />;

/** The first of `stills` that can be drawn, blurred and dimmed (nothing when none can). */
const HeldStill: React.FC<{ stills: string[] }> = ({ stills }) => (stills.length ? (
  <SafeImg src={stills[0]} fallback={<HeldStill stills={stills.slice(1)} />}
    style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scale(1.12)",
      filter: "blur(18px) brightness(0.72) saturate(0.9)" }} />
) : null);

/**
 * A held picture: the first of `still` (one, or several in order of preference) that can be drawn, blurred
 * and dimmed over the dark field - just the field when none can.
 */
export const BlurredHold: React.FC<{ still?: string | string[] }> = ({ still }) => {
  const stills = (Array.isArray(still) ? still : [still]).filter((s, i, all): s is string => Boolean(s)
    && all.indexOf(s) === i);
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: HOLD_FIELD }}>
      <HeldStill stills={stills} />
    </AbsoluteFill>
  );
};
