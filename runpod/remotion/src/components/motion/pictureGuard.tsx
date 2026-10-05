import React from "react";
import { AbsoluteFill, Img, continueRender, delayRender, useCurrentFrame, useVideoConfig } from "remotion";
import type { Overlay, SceneMedia } from "../../types";
import { GROTESK, GROTESK_CAP, SUBLINE } from "../fonts";
import { clamp01, cubicOut, expoOut, idle, prog } from "./ease";

/**
 * A picture look never shows an empty box (the owner, 2026-10-05: "some
 * images in the overlay animations are not showing - not loading while the
 * video plays ... figure out a way to replace them"). Before an image look
 * draws, each of its pictures is loaded once (a real decode, at least 32 px a
 * side); a picture that fails (a hotlink refused, an expired link, a 404, an
 * error page) is dropped from the look, and when none is left the look is
 * drawn as the fallback: the scene's own picture, blurred and dimmed, with the
 * look's words on it in the kinetic type (a kicker and a line), so the moment
 * still reads and nothing is blank. A failed picture also never reaches a
 * remotion <Img> without an error handler (which would stop the render).
 */
const MIN_SIDE = 32;
const PROBE_TIMEOUT_MS = 25000;
const known = new Map<string, boolean>();
const pending = new Map<string, Promise<boolean>>();

const probe = (url: string): Promise<boolean> => {
  if (known.has(url)) return Promise.resolve(Boolean(known.get(url)));
  const had = pending.get(url);
  if (had) return had;
  const p = new Promise<boolean>((resolve) => {
    let done = false;
    const finish = (ok: boolean) => {
      if (done) return;
      done = true;
      known.set(url, ok);
      pending.delete(url);
      resolve(ok);
    };
    try {
      const im = new Image();
      im.onload = () => finish(im.naturalWidth >= MIN_SIDE && im.naturalHeight >= MIN_SIDE);
      im.onerror = () => finish(false);
      im.src = url;
    } catch {
      finish(false);
    }
    setTimeout(() => finish(false), PROBE_TIMEOUT_MS);
  });
  pending.set(url, p);
  return p;
};

/** The usable pictures of `media` once known (null while any is still loading). */
const settled = (media: SceneMedia[]): SceneMedia[] | null => {
  if (!media.every((m) => known.has(m.url))) return null;
  return media.filter((m) => known.get(m.url));
};

export const usePictures = (media: SceneMedia[] | null): SceneMedia[] | null => {
  const urls = (media || []).map((m) => m.url).join("\n");
  const [ok, setOk] = React.useState<SceneMedia[] | null>(() => (media && media.length ? settled(media) : media));
  const [handle] = React.useState(() => (media && media.length && !settled(media)
    ? delayRender(`Checking ${media.length} overlay picture(s)`, { timeoutInMilliseconds: PROBE_TIMEOUT_MS + 15000 }) : null));
  React.useEffect(() => {
    if (!media || !media.length) return;
    let live = true;
    Promise.all(media.map((m) => probe(m.url))).then(() => {
      if (live) setOk(settled(media) || []);
      if (handle !== null) continueRender(handle);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urls]);
  return ok;
};

/** The look's words for the fallback: a short kicker and one line. */
const wordsOf = (ov: Overlay): { kicker: string; line: string } => {
  const s = (v: unknown) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "");
  const line = s(ov.text) || s(ov.subtitle) || s(ov.label);
  const kicker = s(ov.label) && s(ov.label) !== line ? s(ov.label) : s(ov.subtitle) && s(ov.subtitle) !== line ? s(ov.subtitle) : "";
  return { kicker: kicker.length <= 40 ? kicker : "", line: line.length <= 90 ? line : `${line.slice(0, 87).replace(/\s+\S*$/, "")}...` };
};

/**
 * The fallback for a picture look whose pictures all failed: the scene's own
 * picture (its still, or its clip's thumbnail) blurred and dimmed - the clip
 * under it shows through the edges - and the look's words, low left.
 */
export const PictureFallback: React.FC<{ overlay: Overlay; still: string; accent: string }> = ({ overlay, still, accent }) => {
  const f = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames: dur } = useVideoConfig();
  const S = fps / 30;
  const k = W / 1920;
  const { kicker, line } = wordsOf(overlay);
  const [stillOk, setStillOk] = React.useState(true);
  const p = prog(f, 0, 14, S, cubicOut);
  const drift = idle(f, 0, dur);
  const kSize = (0.0175 * H) / GROTESK_CAP;
  const lSize = (0.044 * H) / GROTESK_CAP;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: 0.92 * p, background: "#0b0d11" }}>
        {still && stillOk ? (
          <Img src={still} onError={() => setStillOk(false)} maxRetries={1}
            style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${(1.12 + 0.04 * drift).toFixed(4)})`,
              filter: "blur(22px) brightness(0.55) saturate(0.85)" }} />
        ) : (
          <AbsoluteFill style={{ background: "radial-gradient(ellipse at 40% 45%, #1d2026 0%, #101216 60%, #0b0d11 100%)" }} />
        )}
        <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(8,10,14,.55) 0%, rgba(8,10,14,.1) 60%, transparent 100%)" }} />
      </AbsoluteFill>
      {line ? (
        <div style={{ position: "absolute", left: 0.068 * W, bottom: 0.16 * H, maxWidth: 0.5 * W,
          transform: `translateY(${((1 - prog(f, 4, 16, S, expoOut)) * 18 * k).toFixed(2)}px)`, opacity: prog(f, 4, 12, S, cubicOut) }}>
          {kicker ? (
            <div style={{ fontFamily: SUBLINE, fontWeight: 700, fontSize: kSize, letterSpacing: "0.2em", textTransform: "uppercase",
              color: accent, marginBottom: 16 * k }}>{kicker}</div>
          ) : null}
          <div style={{ height: 3 * k, width: 64 * k, background: accent, borderRadius: 2 * k, marginBottom: 16 * k,
            transformOrigin: "left", transform: `scaleX(${clamp01(prog(f, 6, 16, S, expoOut)).toFixed(4)})` }} />
          <div style={{ fontFamily: GROTESK, fontWeight: 700, fontSize: lSize, lineHeight: 1.08, color: "#FAFAF7",
            letterSpacing: "-0.012em", textShadow: `0 ${2 * k}px ${18 * k}px rgba(0,0,0,.55)` }}>{line}</div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/**
 * Draws `render(pictures)` once the look's pictures are checked: with the ones
 * that load, or the fallback when none does.
 */
export const PictureGuard: React.FC<{ media: SceneMedia[]; overlay: Overlay; still: string; accent: string;
  render: (pictures: SceneMedia[]) => React.ReactNode }> = ({ media, overlay, still, accent, render }) => {
  const ok = usePictures(media);
  if (ok === null) return null;
  if (!ok.length) return <PictureFallback overlay={overlay} still={still} accent={accent} />;
  return <>{render(ok)}</>;
};
