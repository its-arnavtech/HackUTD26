// Motion for the desk: inertial scrolling (Lenis), reveal-on-scroll, a masthead that tucks away
// while reading, and scroll progress for the "how a check works" section. Every piece checks
// prefers-reduced-motion and quietly does nothing in environments without the browser APIs (tests).
import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import Lenis from "lenis";

let lenis: Lenis | null = null;

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Smooth, slightly weighted wheel scrolling for the whole page. Touch keeps the native feel. */
export function useSmoothScroll() {
  useEffect(() => {
    if (prefersReducedMotion() || typeof window.requestAnimationFrame !== "function") return;
    // allowNestedScroll lets the gallery's phone screens and wide tables keep their own wheel scrolling.
    const instance = new Lenis({ lerp: 0.085, wheelMultiplier: 0.95, smoothWheel: true, allowNestedScroll: true });
    lenis = instance;
    let frame = 0;
    const raf = (time: number) => {
      instance.raf(time);
      frame = requestAnimationFrame(raf);
    };
    frame = requestAnimationFrame(raf);
    return () => {
      cancelAnimationFrame(frame);
      instance.destroy();
      if (lenis === instance) lenis = null;
    };
  }, []);
}

/** Jump to the top on a page change, without a long smooth scroll back up. */
export function scrollToTop() {
  if (lenis) lenis.scrollTo(0, { immediate: true, force: true });
  else if (typeof window.scrollTo === "function") window.scrollTo(0, 0);
}

/** Smooth-scroll to an element on the page (in-page links such as "How a check works"). */
export function scrollToElement(id: string) {
  const target = document.getElementById(id);
  if (!target) return;
  if (lenis) lenis.scrollTo(target, { offset: -24, duration: 1.4 });
  else target.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

/** Freeze page scrolling while the index is open. */
export function holdScroll(held: boolean) {
  if (lenis) {
    if (held) lenis.stop();
    else lenis.start();
  }
  document.documentElement.classList.toggle("is-held", held);
}

/** Blocks that rise into place as they enter the viewport. Order on the page sets the stagger. */
const REVEAL = [
  ".page-title",
  ".inbox-caption",
  ".inbox-message",
  ".inbox-assurance",
  ".message-bubble",
  ".result-card",
  ".recovery-link",
  ".privacy-banner",
  ".redacted-message",
  ".redaction-counts",
  ".privacy-recipient",
  ".storage-note",
  ".soft-panel",
  ".was-you-card",
  ".checklist-item",
  ".campaign-card",
  ".consent-points > div",
  ".empty-state",
  ".accuracy-heading",
  ".fixture-banner",
  ".metric-cards > article",
  ".table-heading",
  ".table-scroll",
  ".accuracy-method > p",
  ".gallery-item",
  ".starts",
  ".method-step",
  ".method-head",
  ".colophon",
].join(",");

/**
 * Tags matching blocks inside `root` and reveals each one the first time it scrolls into view.
 * Content that arrives later (polling, retries) is picked up by a MutationObserver.
 * Uses a data attribute rather than a class so React's className updates never fight it.
 */
export function useReveal(root: RefObject<HTMLElement | null>, key: string) {
  useLayoutEffect(() => {
    const host = root.current;
    if (!host) return;
    if (prefersReducedMotion() || typeof IntersectionObserver === "undefined") return;

    let batch = 0;
    let batchTimer: ReturnType<typeof setTimeout> | undefined;
    const seen = new WeakSet<Element>();

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const el = entry.target as HTMLElement;
          el.style.setProperty("--rv-delay", `${Math.min(batch, 6) * 75}ms`);
          el.dataset.rv = "in";
          batch += 1;
          io.unobserve(el);
        }
        clearTimeout(batchTimer);
        batchTimer = setTimeout(() => (batch = 0), 120);
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );

    const tag = () => {
      host.querySelectorAll<HTMLElement>(REVEAL).forEach((el) => {
        if (seen.has(el)) return;
        seen.add(el);
        el.dataset.rv = "wait";
        io.observe(el);
      });
    };

    tag();
    const mo = new MutationObserver(tag);
    mo.observe(host, { childList: true, subtree: true });
    return () => {
      mo.disconnect();
      io.disconnect();
      clearTimeout(batchTimer);
    };
  }, [root, key]);
}

/** True while the reader scrolls down past the fold; false as soon as they scroll back up. */
export function useTuckedOnScroll(threshold = 140) {
  const [state, setState] = useState({ tucked: false, scrolled: false });
  useEffect(() => {
    let last = window.scrollY;
    let frame = 0;
    const update = () => {
      frame = 0;
      const y = window.scrollY;
      const delta = y - last;
      if (Math.abs(delta) < 4) return;
      setState((current) => {
        const tucked = y > threshold && delta > 0;
        const scrolled = y > 8;
        return current.tucked === tucked && current.scrolled === scrolled ? current : { tucked, scrolled };
      });
      last = y;
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [threshold]);
  return state;
}

/**
 * Writes how far `el` has travelled through the viewport (0 at its top entering the middle of
 * the screen, 1 at its bottom reaching the middle) into the CSS variable `--progress`.
 */
export function useScrollProgress(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion()) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const box = el.getBoundingClientRect();
      const middle = window.innerHeight * 0.55;
      const p = Math.min(1, Math.max(0, (middle - box.top) / Math.max(box.height, 1)));
      el.style.setProperty("--progress", p.toFixed(4));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref]);
}
