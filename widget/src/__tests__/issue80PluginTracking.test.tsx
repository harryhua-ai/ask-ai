import { describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { ContextualNudge, EntryPill } from "../components/EntrySurfaces";
import { Launcher, LauncherPill } from "../launcher/Launcher";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

type HostSignal = {
  event_name: "element_click";
  track_category: string;
  track_type: string;
  track_name: string;
};

type EntryCase = {
  name: string;
  selector: string;
  render: () => string;
};

const ENTRY_CASES: EntryCase[] = [
  {
    name: "launcher FAB",
    selector: ".ask-ai-fab",
    render: () =>
      renderToString(
        <Launcher
          icon="current"
          shape="rounded-square"
          theme="light"
          label="Open Ask AI"
          onOpen={() => {}}
        />,
      ),
  },
  {
    name: "launcher pill",
    selector: ".ask-ai-launcher-pill",
    render: () =>
      renderToString(
        <LauncherPill theme="light" label="Open Ask AI" onOpen={() => {}} />,
      ),
  },
  {
    name: "minimal entry pill",
    selector: ".ask-ai-pill",
    render: () => renderToString(<EntryPill label="Ask AI" onOpen={() => {}} />),
  },
  {
    name: "contextual nudge body",
    selector: ".ask-ai-nudge-body",
    render: () =>
      renderToString(
        <ContextualNudge
          greeting="How can I help?"
          dismissLabel="Not now"
          onOpen={() => {}}
          onDismiss={() => {}}
        />,
      ),
  },
];

function installHostDelegatedTracker(
  doc: Document,
  onSignal: (signal: HostSignal) => void,
): () => void {
  const onClick = (event: Event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const entry = target.closest<HTMLElement>("[data-track][data-type]");
    if (!entry) return;
    const trackCategory = entry.dataset.track;
    const trackType = entry.dataset.type;
    if (!trackCategory || !trackType) return;
    onSignal({
      event_name: "element_click",
      track_category: trackCategory,
      track_type: trackType,
      track_name: trackType,
    });
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}

function mountMarkup(markup: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = markup;
  document.body.appendChild(host);
  return host;
}

function click(element: Element): void {
  element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
}

describe("Issue #80 plugin click-tracking contract", () => {
  it("TEST-1: every documented Ask AI entry exposes the frozen semantic attributes", () => {
    for (const entryCase of ENTRY_CASES) {
      const host = mountMarkup(entryCase.render());
      const entry = host.querySelector<HTMLElement>(entryCase.selector);
      expect(entry, entryCase.name).not.toBeNull();
      expect(entry!.dataset.track, entryCase.name).toBe("contact");
      expect(entry!.dataset.type, entryCase.name).toBe("ask_ai");
      host.remove();
    }
  });

  it("TEST-2: a generic host delegated listener observes the launcher interaction", () => {
    const signals: HostSignal[] = [];
    const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
    const host = mountMarkup(ENTRY_CASES[0].render());
    click(host.querySelector(ENTRY_CASES[0].selector)!);
    removeTracker();
    host.remove();
    expect(signals).toHaveLength(1);
  });

  it("TEST-3: the host derives the canonical element_click payload from the attributes", () => {
    const signals: HostSignal[] = [];
    const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
    const host = mountMarkup(ENTRY_CASES[1].render());
    click(host.querySelector(ENTRY_CASES[1].selector)!);
    removeTracker();
    host.remove();
    expect(signals).toEqual([
      {
        event_name: "element_click",
        track_category: "contact",
        track_type: "ask_ai",
        track_name: "ask_ai",
      },
    ]);
  });

  it("TEST-4: one physical interaction produces exactly one canonical host signal", () => {
    for (const entryCase of ENTRY_CASES) {
      const signals: HostSignal[] = [];
      const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
      const host = mountMarkup(entryCase.render());
      click(host.querySelector(entryCase.selector)!);
      removeTracker();
      host.remove();
      expect(signals, entryCase.name).toHaveLength(1);
      expect(signals[0].track_type, entryCase.name).toBe("ask_ai");
    }
  });

  it("TEST-5: another contact CTA remains isolated from Ask AI", () => {
    const signals: HostSignal[] = [];
    const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
    const host = mountMarkup(
      '<button data-track="contact" data-type="email">Email</button>',
    );
    click(host.querySelector("button")!);
    removeTracker();
    host.remove();
    expect(signals).toHaveLength(1);
    expect(signals[0].track_type).toBe("email");
    expect(signals.some((signal) => signal.track_type === "ask_ai")).toBe(false);
  });

  it("TEST-6: adding tracking semantics preserves the launcher open callback", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    let openCalls = 0;
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <LauncherPill
          theme="light"
          label="Open Ask AI"
          onOpen={() => {
            openCalls += 1;
          }}
        />,
      );
    });
    await act(async () => {
      click(host.querySelector(".ask-ai-launcher-pill")!);
    });
    root.unmount();
    host.remove();
    expect(openCalls).toBe(1);
  });

  it("TEST-7: the host contract works without GA4, GTM, or Analytics credentials", () => {
    const signals: HostSignal[] = [];
    const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
    const host = mountMarkup(ENTRY_CASES[2].render());
    click(host.querySelector(ENTRY_CASES[2].selector)!);
    removeTracker();
    host.remove();
    expect(signals[0]).toMatchObject({ track_category: "contact", track_type: "ask_ai" });
  });

  it("TEST-8: semantic tracking is independent of button class, label, and DOM position", () => {
    const signals: HostSignal[] = [];
    const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
    const host = mountMarkup(
      '<section><div><button class="unrelated-class" data-track="contact" data-type="ask_ai"><span>Open assistant</span></button></div></section>',
    );
    click(host.querySelector("span")!);
    removeTracker();
    host.remove();
    expect(signals).toEqual([
      {
        event_name: "element_click",
        track_category: "contact",
        track_type: "ask_ai",
        track_name: "ask_ai",
      },
    ]);
  });

  it("TEST-9: the Ask AI click reaches the host without being default-prevented", () => {
    const signals: HostSignal[] = [];
    const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
    const host = mountMarkup(ENTRY_CASES[3].render());
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    host.querySelector(ENTRY_CASES[3].selector)!.dispatchEvent(event);
    removeTracker();
    host.remove();
    expect(event.defaultPrevented).toBe(false);
    expect(signals).toHaveLength(1);
  });

  it("TEST-10: the documented anchor form has the same public contract as a button launcher", () => {
    const signals: HostSignal[] = [];
    const removeTracker = installHostDelegatedTracker(document, (signal) => signals.push(signal));
    const host = mountMarkup(
      '<a href="/ask-ai/" data-track="contact" data-type="ask_ai">Ask AI</a>',
    );
    // The synthetic host owns navigation policy; prevent jsdom's unimplemented
    // document navigation while leaving event propagation observable.
    host.addEventListener("click", (event) => event.preventDefault());
    click(host.querySelector("a")!);
    removeTracker();
    host.remove();
    expect(signals).toEqual([
      {
        event_name: "element_click",
        track_category: "contact",
        track_type: "ask_ai",
        track_name: "ask_ai",
      },
    ]);
  });
});
