/**
 * OCR data extracted by tesseract-cli from public/article.png
 * Command: tesseract public/article.png /tmp/article_ocr --oem 1 --psm 1 hocr txt
 *
 * Image dimensions: 900 x 1200 px
 * All coordinates are in image pixel space.
 */

export const IMAGE_WIDTH = 900;
export const IMAGE_HEIGHT = 1200;

export interface OcrBox {
  /** Left edge in image px */
  x: number;
  /** Top edge in image px */
  y: number;
  /** Width in image px */
  w: number;
  /** Height in image px */
  h: number;
  /** Label for debugging */
  label: string;
}

/**
 * Bounding boxes for "government shutdown" – headline occurrence (largest text)
 * tesseract hOCR bbox: (343, 111, 726, 144)
 */
export const GOVERNMENT_SHUTDOWN_BOXES: OcrBox[] = [
  { x: 343, y: 111, w: 383, h: 33, label: "government shutdown (headline)" },
];

/**
 * Bounding boxes for "funding lapses" – headline occurrence (largest text)
 * tesseract hOCR bbox: (51, 148, 303, 181)
 */
export const FUNDING_LAPSES_BOXES: OcrBox[] = [
  { x: 51, y: 148, w: 252, h: 33, label: "funding lapses (headline)" },
];

/** All highlight targets in order of appearance */
export const ALL_HIGHLIGHT_BOXES: OcrBox[] = [
  ...GOVERNMENT_SHUTDOWN_BOXES,
  ...FUNDING_LAPSES_BOXES,
];
