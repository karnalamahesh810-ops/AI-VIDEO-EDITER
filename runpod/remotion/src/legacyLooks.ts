import type { Overlay } from "./types";

/**
 * Retired looks, drawn as their clean replacement (the owner, 2026-10-05,
 * on the big yellow / white condensed words with a thick black outline - the
 * "15 TIMES" and the boxed "ALMOST 15" of his Las Vegas video: "I don't want
 * this animation at all in our library. Remove it. It looks cheap, like a
 * CapCut font"). The planner never picks these ids again and the editor's
 * picker hides them (registry "retired": true); a document saved before
 * still names them, so here each is drawn as the kinetic-type look that says
 * the same thing (LibKinetic "kt-"): a number as a figure, "15 times" as a
 * multiplier, a share as a ring, a date as a date, words as a key phrase or a
 * typed statement. The document is not changed (the relook action rewrites
 * it for good). scripts/build_registry.py keeps the same list (RETIRED).
 */
export const RETIRED_IDS = [
  // the outlined condensed words and figures, and the boxed stack (LibEditorText, LibBoldText)
  "LIB_ED_WORD_BY_WORD", "LIB_ED_BOX_STACK", "LIB_ED_TYPE_CLEAN", "LIB_ED_TYPE_TERMINAL", "LIB_ED_MARKER_HIGHLIGHT",
  "LIB_ED_BLUR_IN", "LIB_ED_SPLIT_REVEAL", "LIB_ED_OUTLINE_FILL", "LIB_ED_QUOTE_TYPE", "LIB_ED_QUESTION",
  "LIB_BT_COUNT", "LIB_DT_LETTER_DROP", "LIB_DT_BOLD_HEADLINE", "LIB_DT_BIG_STACK",
  // the condensed headline words with a yellow key word or bar
  "TEXT_WORD_TYPE_V1", "TEXT_BAR_TITLE_V1", "TEXT_UNDERLINE_TITLE_V1", "TEXT_SWOOSH_TITLE_V1",
  "TEXT_SENTENCE_HIGHLIGHT_V1", "TEXT_KEY_PHRASE_V1", "TEXT_KICKER_V1", "TEXT_TYPEWRITER_V1", "TEXT_MEMO_V1",
  "TEXT_QUESTION_V1", "TEXT_LABEL_PILL_V1",
  "LIB_HL_WORD_STACK", "LIB_HL_SPLIT_LINE", "LIB_HL_WIPE_BAR", "LIB_HL_KEYWORD_POP", "LIB_HL_FOCUS_PULL",
  "LIB_HL_LETTER_FLIP", "LIB_HL_OUTLINE_FILL", "LIB_HL_MARKER_SWEEP", "LIB_HL_CENTER_STACK", "LIB_HL_TICKER_SLIDE",
  "LIB_TXT_KEY_PHRASE", "LIB_TXT_QUOTE_LINE", "LIB_TXT_HEADLINE_WORDS", "LIB_TXT_QUESTION", "LIB_TXT_UNDERLINE_SWEEP",
  "LIB_TXT_KICKER_HEADLINE", "LIB_QS_ZOOM_WORD",
] as const;
const RETIRED = new Set<string>(RETIRED_IDS);

const TYPED = new Set(["LIB_ED_TYPE_CLEAN", "LIB_ED_TYPE_TERMINAL", "LIB_ED_QUOTE_TYPE", "LIB_ED_QUESTION",
  "TEXT_TYPEWRITER_V1", "TEXT_MEMO_V1", "TEXT_QUESTION_V1", "LIB_TXT_QUOTE_LINE", "LIB_TXT_QUESTION"]);
const DATES = new Set(["LIB_DT_LETTER_DROP", "LIB_DT_BOLD_HEADLINE", "LIB_DT_BIG_STACK"]);

const WORDNUM: Record<string, number> = {
  one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11,
  twelve: 12, fifteen: 15, twenty: 20, twice: 2, double: 2, triple: 3, half: 0.5,
};
const MULT = /\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)\s*(?:times|x|×)\b|\b(twice|double|triple)\b/i;
const MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december";
const DATE = new RegExp(`\\b(${MONTHS})\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:,?\\s*((?:1[5-9]|20)\\d\\d))?`, "i");
const MONTH_YEAR = new RegExp(`\\b(${MONTHS})\\s*,?\\s*((?:1[5-9]|20)\\d\\d)\\b`, "i");
const BARE_NUMBER = /^(?:(almost|about|nearly|roughly|over|more than|under|less than)\s+)?(\d[\d,]*(?:\.\d+)?)\s*$/i;

const title = (s: string) => s.toLowerCase().replace(/(^|\s)([a-z])/g, (_m, a: string, b: string) => a + b.toUpperCase());
const kt = (ov: Overlay, variant: string, props: Partial<Overlay>): Overlay => ({
  ...ov, ...props, type: "motion", variant, template: variant.toUpperCase().replace(/-/g, "_"), // KT_NUMBER, KT_MULTIPLIER, ... (the registry ids)
  motion: "fade", exit: "fade", textStyle: undefined, align: undefined,
} as Overlay);

/** The clean look a retired overlay is drawn as (the overlay itself when it is not retired). */
export const remapRetired = (ov: Overlay): Overlay => {
  const id = String(ov?.template || "");
  if (!RETIRED.has(id)) return ov;
  const text = String(ov.text || "").replace(/\s+/g, " ").trim();
  const value = typeof ov.value === "number" && Number.isFinite(ov.value) ? ov.value : null;
  const suffix = String(ov.suffix || "").trim();
  if (DATES.has(id)) {
    const m = DATE.exec(text);
    if (m) return kt(ov, "kt-date", { text: `${title(m[1])} ${Number(m[2])}`, subtitle: m[3] || "", label: "" });
    const my = MONTH_YEAR.exec(text);
    if (my) return kt(ov, "kt-date", { text: title(my[1]), subtitle: my[2], label: "" });
    return kt(ov, "kt-keyword", { text, label: "" });
  }
  if (value !== null && (id === "LIB_BT_COUNT" || id === "TEXT_LABEL_PILL_V1")) {
    const word = text.toLowerCase();
    if (suffix === "%") return kt(ov, "kt-percent", { value, suffix: "%", label: "", subtitle: word });
    if (id === "TEXT_LABEL_PILL_V1") return kt(ov, "kt-chip", { value, suffix, label: text });
    const scaleWord = /^(million|billion|thousand)$/i.test(suffix);
    return kt(ov, "kt-number", scaleWord ? { value, suffix, label: "", subtitle: word }
      : { value, suffix, label: text });
  }
  const mult = MULT.exec(text);
  if (mult) {
    const n = mult[1] ? (/^\d/.test(mult[1]) ? Number(mult[1]) : WORDNUM[mult[1].toLowerCase()]) : WORDNUM[(mult[2] || "").toLowerCase()];
    if (n && Number.isFinite(n)) return kt(ov, "kt-multiplier", { value: n, suffix: "×", label: "", subtitle: "" });
  }
  const bare = BARE_NUMBER.exec(text);
  if (bare) {
    const n = Number(bare[2].replace(/,/g, ""));
    if (Number.isFinite(n)) return kt(ov, "kt-number", { value: n, suffix: "", label: bare[1] ? bare[1].toUpperCase() : "", subtitle: "" });
  }
  if (TYPED.has(id) || text.split(" ").length > 6) {
    return kt(ov, "kt-statement", { text, label: /QUESTION/i.test(id) || /\?\s*$/.test(text) ? "The question" : "" });
  }
  return kt(ov, "kt-keyword", { text, label: String(ov.subtitle || ov.label || "").length <= 28 ? String(ov.subtitle || ov.label || "") : "" });
};

export const isRetired = (id?: string) => RETIRED.has(String(id || ""));
