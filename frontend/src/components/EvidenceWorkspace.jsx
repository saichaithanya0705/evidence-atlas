import { useCallback, useEffect, useRef, useState } from "react";
import EvidenceOverview from "./EvidenceOverview.jsx";
import EvidencePaperTab from "./EvidencePaperTab.jsx";

export default function EvidenceWorkspace({ workspace }) {
  const rootRef = useRef(null);
  const tabRefs = useRef(new Map());
  const savedFocus = useRef(null);
  const savedOverflow = useRef("");
  const inertSiblings = useRef([]);
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 768);
  const width = workspace.panelWidth;
  const activeIndex = workspace.tabs.findIndex(tab => tab.id === workspace.activeTabId);
  const activeTab = workspace.tabs[activeIndex] || workspace.tabs[0];

  useEffect(() => {
    const update = () => {
      const mobile = window.innerWidth <= 768;
      setIsMobile(mobile);
      if (!mobile) workspace.setPanelWidth(current => Math.min(current, window.innerWidth / 2, 760));
    };
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [workspace.setPanelWidth]);

  const closeMobile = useCallback(() => workspace.toggle(), [workspace.toggle]);
  useEffect(() => {
    if (!workspace.isOpen || !isMobile) return undefined;
    savedFocus.current = document.activeElement;
    const focusFirst = window.requestAnimationFrame(() => rootRef.current?.querySelector("button, [href], [tabindex='0']")?.focus());
    savedOverflow.current = document.body.style.overflow;
    const backdrop = rootRef.current?.previousElementSibling;
    for (const sibling of [...(rootRef.current?.parentElement?.children || [])]) {
      if (sibling !== rootRef.current && sibling !== backdrop) {
        inertSiblings.current.push([sibling, sibling.inert]);
        sibling.inert = true;
      }
    }
    const onKeyDown = event => {
      if (event.key === "Escape") { event.preventDefault(); closeMobile(); return; }
      if (event.key !== "Tab") return;
      const nodes = [...(rootRef.current?.querySelectorAll("button:not([disabled]), a[href], [tabindex='0']") || [])].filter(node => node.getClientRects().length);
      if (!nodes.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      cancelAnimationFrame(focusFirst);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = savedOverflow.current;
      for (const [sibling, wasInert] of inertSiblings.current) sibling.inert = wasInert;
      inertSiblings.current = [];
      savedFocus.current?.focus?.();
    };
  }, [workspace.isOpen, isMobile, closeMobile]);

  const onResizeKeyDown = useCallback(event => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      workspace.setPanelWidth(width + (event.key === "ArrowLeft" ? 24 : -24));
    } else if (event.key === "Home") { event.preventDefault(); workspace.setPanelWidth(360); }
    else if (event.key === "End") { event.preventDefault(); workspace.setPanelWidth(Math.min(window.innerWidth / 2, 760)); }
  }, [width, workspace.setPanelWidth]);

  const onPointerDown = useCallback(event => {
    if (event.button !== 0) return;
    event.preventDefault();
    const separator = event.currentTarget;
    separator.setPointerCapture(event.pointerId);
    const updateTransientWidth = moveEvent => {
      const maximum = Math.min(760, Math.floor(window.innerWidth / 2));
      const next = Math.min(maximum, Math.max(360, window.innerWidth - moveEvent.clientX));
      rootRef.current?.style.setProperty("--evidence-workspace-width", `${next}px`);
      separator.setAttribute("aria-valuenow", String(Math.round(next)));
    };
    const onUp = () => {
      workspace.setPanelWidth(rootRef.current?.getBoundingClientRect().width || width);
      separator.removeEventListener("pointermove", updateTransientWidth);
      separator.removeEventListener("pointerup", onUp);
      separator.removeEventListener("pointercancel", onUp);
    };
    separator.addEventListener("pointermove", updateTransientWidth);
    separator.addEventListener("pointerup", onUp);
    separator.addEventListener("pointercancel", onUp);
  }, [workspace.setPanelWidth]);

  function onTabKeyDown(event, index) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % workspace.tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + workspace.tabs.length) % workspace.tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = workspace.tabs.length - 1;
    else return;
    event.preventDefault();
    const tab = workspace.tabs[next];
    workspace.activateTab(tab.id);
    tabRefs.current.get(tab.id)?.focus();
  }

  return <>
    {workspace.isOpen && isMobile && <button className="evidence-backdrop" type="button" tabIndex={-1} aria-label="Close evidence workspace" onClick={closeMobile} />}
    <aside ref={rootRef} className={`evidence-workspace${workspace.isOpen ? " is-open" : " is-collapsed"}`} style={{ "--evidence-workspace-width": `${width}px` }} role={workspace.isOpen ? "dialog" : undefined} aria-modal={workspace.isOpen && isMobile ? "true" : undefined} aria-label={workspace.isOpen ? "Evidence workspace" : undefined} hidden={!workspace.isOpen}>
      <div className="evidence-workspace-heading"><span className="eyebrow">EVIDENCE ATLAS / SOURCE RECORD</span><div><h2>Evidence workspace</h2><button className="icon-button evidence-mobile-close" type="button" aria-label="Close evidence workspace" onClick={closeMobile}>×</button></div></div>
      <div className="evidence-tabstrip" role="tablist" aria-label="Evidence workspace tabs">
        {workspace.tabs.map((tab, index) => <div className="evidence-tab-item" key={tab.id}>
          <button ref={node => { if (node) tabRefs.current.set(tab.id, node); else tabRefs.current.delete(tab.id); }} id={`evidence-tab-${encodeURIComponent(tab.id)}`} type="button" role="tab" aria-selected={tab.id === workspace.activeTabId} aria-controls={`evidence-panel-${encodeURIComponent(tab.id)}`} tabIndex={tab.id === workspace.activeTabId ? 0 : -1} onClick={() => workspace.activateTab(tab.id)} onKeyDown={event => onTabKeyDown(event, index)}>{tab.title}</button>
          {tab.type === "paper" && <button type="button" className="evidence-tab-close" aria-label={`Close ${tab.title}`} onClick={() => workspace.closePaper(tab.id)}>×</button>}
        </div>)}
      </div>
      <section id={`evidence-panel-${encodeURIComponent(activeTab.id)}`} className="evidence-tabpanel" role="tabpanel" aria-labelledby={`evidence-tab-${encodeURIComponent(activeTab.id)}`} tabIndex={0}>
        {activeTab.type === "overview" ? <EvidenceOverview sourceCount={workspace.tabs.length - 1} onOpenFirst={() => workspace.activateTab(workspace.tabs[1]?.id)} /> : <EvidencePaperTab key={activeTab.id} tab={activeTab} />}
      </section>
      {workspace.tabs.length > 1 && <div className="evidence-workspace-footer">{workspace.tabs.length - 1} source{workspace.tabs.length === 2 ? "" : "s"} saved for this conversation</div>}
      <div className="evidence-resize" role="separator" aria-label="Resize evidence workspace" aria-orientation="vertical" aria-valuemin="360" aria-valuemax={Math.min(760, Math.floor(window.innerWidth / 2))} aria-valuenow={Math.round(width)} tabIndex={0} onKeyDown={onResizeKeyDown} onPointerDown={onPointerDown} />
    </aside>
  </>;
}
