import { useCallback, useEffect, useMemo, useState } from "react";

const sessionMemory = new Map();
const emptyWorkspace = () => ({ isOpen: false, activeTabId: "overview", tabs: [{ id: "overview", type: "overview", title: "Overview" }], panelWidth: Math.min(520, Math.floor(window.innerWidth / 2)) });

function normalizedPmid(value) {
  const digits = String(value ?? "").trim().replace(/^pmid:\s*/i, "").replace(/\s+/g, "");
  return digits || "unknown";
}

export default function useEvidenceWorkspace(conversationId) {
  const key = conversationId || "__new_conversation__";
  const [snapshot, setSnapshot] = useState(() => ({ key, value: sessionMemory.get(key) || emptyWorkspace() }));
  const workspace = snapshot.key === key ? snapshot.value : sessionMemory.get(key) || emptyWorkspace();

  useEffect(() => {
    if (snapshot.key === key) sessionMemory.set(key, snapshot.value);
  }, [key, snapshot]);

  const update = useCallback((updater) => {
    setSnapshot(currentSnapshot => {
      const current = currentSnapshot.key === key ? currentSnapshot.value : sessionMemory.get(key) || emptyWorkspace();
      const next = typeof updater === "function" ? updater(current) : updater;
      sessionMemory.set(key, next);
      return { key, value: next };
    });
  }, [key]);

  const openOverview = useCallback(() => update(current => ({ ...current, isOpen: true, activeTabId: "overview" })), [update]);
  const openPaper = useCallback(({ paper, turnId, evidenceId, spanText } = {}) => {
    if (!paper?.pmid) return;
    const pmid = normalizedPmid(paper.pmid);
    const id = `pmid:${pmid}`;
    update(current => {
      const previous = current.tabs.find(tab => tab.id === id);
      const refs = previous?.references || [];
      const reference = { turnId, evidenceId, spanText };
      const references = (turnId || spanText || evidenceId) && !refs.some(item => item.turnId === turnId && item.evidenceId === evidenceId && item.spanText === spanText)
        ? [...refs, reference]
        : refs;
      const oldRecords = previous?.paper?.evidenceRecords || [];
      const mergedRecords = [...oldRecords];
      for (const record of paper.evidenceRecords || []) if (!mergedRecords.some(item => item.pmid === record.pmid && item.key_findings === record.key_findings && JSON.stringify(item.supporting_text_spans) === JSON.stringify(record.supporting_text_spans))) mergedRecords.push(record);
      const nextPaper = { ...(previous?.paper || {}), ...paper, evidenceRecords: mergedRecords, pmid };
      const tab = { id, type: "paper", title: nextPaper.title || `PMID ${pmid}`, paper: nextPaper, selectedSpan: spanText || previous?.selectedSpan || "", selectedReference: reference, references };
      const tabs = previous ? current.tabs.map(item => item.id === id ? tab : item) : [...current.tabs, tab];
      return { ...current, tabs, activeTabId: id, isOpen: true };
    });
  }, [update]);
  const closePaper = useCallback((id) => update(current => {
    const index = current.tabs.findIndex(tab => tab.id === id);
    if (index <= 0) return current;
    const tabs = current.tabs.filter(tab => tab.id !== id);
    const activeTabId = current.activeTabId === id ? tabs[Math.min(index, tabs.length - 1)].id : current.activeTabId;
    return { ...current, tabs, activeTabId };
  }), [update]);
  const activateTab = useCallback((id) => update(current => current.tabs.some(tab => tab.id === id) ? { ...current, activeTabId: id, isOpen: true } : current), [update]);
  const toggle = useCallback(() => update(current => ({ ...current, isOpen: !current.isOpen })), [update]);
  const setPanelWidth = useCallback((value) => update(current => {
    const maximum = Math.min(760, Math.floor(window.innerWidth / 2));
    const requested = typeof value === "function" ? value(current.panelWidth) : value;
    return { ...current, panelWidth: Math.min(maximum, Math.max(360, Number(requested) || current.panelWidth)) };
  }), [update]);

  useEffect(() => {
    const handleToggle = () => toggle();
    window.addEventListener("evidence-workspace-toggle", handleToggle);
    return () => window.removeEventListener("evidence-workspace-toggle", handleToggle);
  }, [toggle]);

  return useMemo(() => ({ ...workspace, openOverview, openPaper, closePaper, activateTab, toggle, setPanelWidth }), [workspace, openOverview, openPaper, closePaper, activateTab, toggle, setPanelWidth]);
}
