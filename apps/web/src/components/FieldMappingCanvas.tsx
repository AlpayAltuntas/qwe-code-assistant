import { Search, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FieldRef, FieldSource, SourceField } from "../api";

function encodeRef(f: SourceField | FieldRef): string {
  return JSON.stringify({ parent_tag: f.parent_tag, tag: f.tag, occurrence: f.occurrence });
}

export interface CanvasTargetField {
  field: string;
  label: string;
}

export interface CanvasTargetSection {
  title: string | null;
  fields: CanvasTargetField[];
}

interface FieldMappingCanvasProps {
  sourceFields: SourceField[];
  targetSections: CanvasTargetSection[];
  values: Record<string, FieldSource | undefined>;
  onChange: (field: string, source: FieldSource | undefined) => void;
  sourceHeading: string;
  targetHeading: string;
}

interface Line {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function rectVisibleWithin(rowRect: DOMRect, panelRect: DOMRect): boolean {
  return rowRect.bottom > panelRect.top && rowRect.top < panelRect.bottom;
}

export function FieldMappingCanvas({
  sourceFields,
  targetSections,
  values,
  onChange,
  sourceHeading,
  targetHeading,
}: FieldMappingCanvasProps) {
  const [sourceFilter, setSourceFilter] = useState("");
  const [targetFilter, setTargetFilter] = useState("");
  const [armedSource, setArmedSource] = useState<SourceField | null>(null);
  const [dragSource, setDragSource] = useState<SourceField | null>(null);
  const [dragPos, setDragPos] = useState<{ x: number; y: number } | null>(null);
  const [hoverTargetField, setHoverTargetField] = useState<string | null>(null);
  const [editingField, setEditingField] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");
  const [lines, setLines] = useState<Line[]>([]);

  const containerRef = useRef<HTMLDivElement>(null);
  const sourcePanelRef = useRef<HTMLDivElement>(null);
  const targetPanelRef = useRef<HTMLDivElement>(null);
  const sourceRowRefs = useRef(new Map<string, HTMLDivElement>());
  const targetRowRefs = useRef(new Map<string, HTMLDivElement>());

  const filteredSourceFields = useMemo(() => {
    const q = sourceFilter.trim().toLowerCase();
    if (!q) return sourceFields;
    return sourceFields.filter((f) => f.label.toLowerCase().includes(q));
  }, [sourceFields, sourceFilter]);

  const filteredTargetSections = useMemo(() => {
    const q = targetFilter.trim().toLowerCase();
    if (!q) return targetSections;
    return targetSections
      .map((s) => ({ ...s, fields: s.fields.filter((f) => f.label.toLowerCase().includes(q)) }))
      .filter((s) => s.fields.length > 0);
  }, [targetSections, targetFilter]);

  const sourceByEncodedRef = useMemo(() => {
    const map = new Map<string, SourceField>();
    for (const f of sourceFields) map.set(encodeRef(f), f);
    return map;
  }, [sourceFields]);

  const connectedRefKeys = useMemo(() => {
    const set = new Set<string>();
    for (const v of Object.values(values)) {
      if (v?.kind === "field") set.add(encodeRef(v.ref));
    }
    return set;
  }, [values]);

  function connect(source: SourceField, targetField: string) {
    onChange(targetField, { kind: "field", ref: { parent_tag: source.parent_tag, tag: source.tag, occurrence: source.occurrence } });
  }

  function disconnect(targetField: string) {
    onChange(targetField, undefined);
  }

  function startEditingConstant(targetField: string, initial: string) {
    setArmedSource(null);
    setEditingField(targetField);
    setDraftValue(initial);
  }

  function commitConstant() {
    if (editingField) onChange(editingField, draftValue.trim() ? { kind: "constant", value: draftValue.trim() } : undefined);
    setEditingField(null);
  }

  function handleSourceClick(sf: SourceField) {
    if (dragSource) return; // a real drag just finished; ignore the trailing click
    setArmedSource((prev) => (prev && encodeRef(prev) === encodeRef(sf) ? null : sf));
  }

  function handleTargetClick(field: string) {
    if (armedSource) {
      connect(armedSource, field);
      setArmedSource(null);
    }
  }

  // Escape cancels an armed source or an in-progress constant edit.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setArmedSource(null);
      setEditingField(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Drag lifecycle: pointerdown on a source row starts it; this effect
  // only re-runs when a drag starts/ends (dragPos updates separately),
  // so the window listeners attach exactly once per drag.
  useEffect(() => {
    if (!dragSource) return;
    function targetFieldAt(x: number, y: number): string | null {
      const el = document.elementFromPoint(x, y) as HTMLElement | null;
      const row = el?.closest("[data-target-field]") as HTMLElement | null;
      return row?.dataset.targetField ?? null;
    }
    function onMove(e: PointerEvent) {
      setDragPos({ x: e.clientX, y: e.clientY });
      setHoverTargetField(targetFieldAt(e.clientX, e.clientY));
    }
    function onUp(e: PointerEvent) {
      const field = targetFieldAt(e.clientX, e.clientY);
      if (field && dragSource) connect(dragSource, field);
      setDragSource(null);
      setDragPos(null);
      setHoverTargetField(null);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragSource]);

  const recomputeLines = useCallback(() => {
    const container = containerRef.current;
    const sourcePanel = sourcePanelRef.current;
    const targetPanel = targetPanelRef.current;
    if (!container || !sourcePanel || !targetPanel) return;

    const containerRect = container.getBoundingClientRect();
    const sourcePanelRect = sourcePanel.getBoundingClientRect();
    const targetPanelRect = targetPanel.getBoundingClientRect();
    const next: Line[] = [];

    for (const [field, source] of Object.entries(values)) {
      if (source?.kind !== "field") continue;
      const sourceField = sourceByEncodedRef.get(encodeRef(source.ref));
      if (!sourceField) continue;
      const sourceEl = sourceRowRefs.current.get(encodeRef(sourceField));
      const targetEl = targetRowRefs.current.get(field);
      if (!sourceEl || !targetEl) continue;

      const sourceRect = sourceEl.getBoundingClientRect();
      const targetRect = targetEl.getBoundingClientRect();
      if (!rectVisibleWithin(sourceRect, sourcePanelRect) || !rectVisibleWithin(targetRect, targetPanelRect)) continue;

      next.push({
        key: field,
        x1: sourceRect.right - containerRect.left,
        y1: sourceRect.top + sourceRect.height / 2 - containerRect.top,
        x2: targetRect.left - containerRect.left,
        y2: targetRect.top + targetRect.height / 2 - containerRect.top,
      });
    }
    setLines(next);
  }, [values, sourceByEncodedRef]);

  useLayoutEffect(() => {
    recomputeLines();
  }, [recomputeLines, filteredSourceFields, filteredTargetSections]);

  useEffect(() => {
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        recomputeLines();
      });
    };
    const sourcePanel = sourcePanelRef.current;
    const targetPanel = targetPanelRef.current;
    sourcePanel?.addEventListener("scroll", onScroll, { passive: true });
    targetPanel?.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      sourcePanel?.removeEventListener("scroll", onScroll);
      targetPanel?.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [recomputeLines]);

  let dragGhost: Line | null = null;
  if (dragSource && dragPos && containerRef.current) {
    const containerRect = containerRef.current.getBoundingClientRect();
    const sourceEl = sourceRowRefs.current.get(encodeRef(dragSource));
    if (sourceEl) {
      const sourceRect = sourceEl.getBoundingClientRect();
      dragGhost = {
        key: "__drag__",
        x1: sourceRect.right - containerRect.left,
        y1: sourceRect.top + sourceRect.height / 2 - containerRect.top,
        x2: dragPos.x - containerRect.left,
        y2: dragPos.y - containerRect.top,
      };
    }
  }

  return (
    <div className={`mapping-canvas ${dragSource ? "dragging" : ""}`} ref={containerRef}>
      <div className="mapping-canvas-panel">
        <div className="mapping-canvas-panel-header">
          <span className="field-group-title" style={{ margin: 0 }}>
            {sourceHeading}
          </span>
        </div>
        <div className="mapping-canvas-filter">
          <Search size={13} />
          <input
            placeholder="Filter…"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
          />
        </div>
        <div className="mapping-canvas-scroll" ref={sourcePanelRef}>
          {filteredSourceFields.map((sf) => {
            const key = encodeRef(sf);
            const isArmed = armedSource !== null && encodeRef(armedSource) === key;
            const isDragging = dragSource !== null && encodeRef(dragSource) === key;
            return (
              <div
                key={key}
                ref={(el) => {
                  if (el) sourceRowRefs.current.set(key, el);
                  else sourceRowRefs.current.delete(key);
                }}
                className={`canvas-row canvas-row-source ${isArmed ? "armed" : ""} ${isDragging ? "dragging" : ""} ${connectedRefKeys.has(key) ? "connected" : ""}`}
                onPointerDown={(e) => {
                  e.preventDefault();
                  setDragSource(sf);
                  setDragPos({ x: e.clientX, y: e.clientY });
                }}
                onClick={() => handleSourceClick(sf)}
                title={sf.label}
              >
                <span className="canvas-row-label">{sf.label}</span>
              </div>
            );
          })}
        </div>
      </div>

      <svg className="mapping-canvas-svg">
        {lines.map((l) => (
          <path
            key={l.key}
            d={`M ${l.x1} ${l.y1} C ${l.x1 + 40} ${l.y1}, ${l.x2 - 40} ${l.y2}, ${l.x2} ${l.y2}`}
            className="mapping-canvas-line"
          />
        ))}
        {dragGhost && (
          <path
            d={`M ${dragGhost.x1} ${dragGhost.y1} C ${dragGhost.x1 + 40} ${dragGhost.y1}, ${dragGhost.x2 - 40} ${dragGhost.y2}, ${dragGhost.x2} ${dragGhost.y2}`}
            className="mapping-canvas-line mapping-canvas-line-ghost"
          />
        )}
      </svg>

      <div className="mapping-canvas-panel">
        <div className="mapping-canvas-panel-header">
          <span className="field-group-title" style={{ margin: 0 }}>
            {targetHeading}
          </span>
        </div>
        <div className="mapping-canvas-filter">
          <Search size={13} />
          <input
            placeholder="Filter…"
            value={targetFilter}
            onChange={(e) => setTargetFilter(e.target.value)}
          />
        </div>
        <div className="mapping-canvas-scroll" ref={targetPanelRef}>
          {filteredTargetSections.map((section) => (
            <div key={section.title ?? "__flat__"}>
              {section.title && (
                <div className="field-group-title" style={{ margin: "10px 0 4px" }}>
                  {section.title}
                </div>
              )}
              {section.fields.map((t) => {
                const source = values[t.field];
                const isHover = hoverTargetField === t.field;
                const isEditing = editingField === t.field;
                return (
                  <div
                    key={t.field}
                    ref={(el) => {
                      if (el) targetRowRefs.current.set(t.field, el);
                      else targetRowRefs.current.delete(t.field);
                    }}
                    data-target-field={t.field}
                    className={`canvas-row canvas-row-target ${isHover ? "drag-hover" : ""} ${source ? "connected" : ""} ${armedSource ? "armable" : ""}`}
                    onClick={() => handleTargetClick(t.field)}
                  >
                    <span className="canvas-row-label">{t.label}</span>
                    <span className="canvas-row-value">
                      {isEditing ? (
                        <input
                          autoFocus
                          className="canvas-value-input"
                          value={draftValue}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => setDraftValue(e.target.value)}
                          onBlur={commitConstant}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                            if (e.key === "Escape") setEditingField(null);
                          }}
                        />
                      ) : source?.kind === "field" ? (
                        <>
                          <span className="canvas-value-chip">
                            {source.ref.parent_tag} / {source.ref.tag}
                          </span>
                          <button
                            className="icon-btn"
                            type="button"
                            title="Remove connection"
                            onClick={(e) => {
                              e.stopPropagation();
                              disconnect(t.field);
                            }}
                          >
                            <X size={12} />
                          </button>
                        </>
                      ) : source?.kind === "constant" ? (
                        <>
                          <span
                            className="canvas-value-chip constant"
                            onClick={(e) => {
                              e.stopPropagation();
                              startEditingConstant(t.field, source.value);
                            }}
                          >
                            {source.value || "(empty)"}
                          </span>
                          <button
                            className="icon-btn"
                            type="button"
                            title="Remove"
                            onClick={(e) => {
                              e.stopPropagation();
                              disconnect(t.field);
                            }}
                          >
                            <X size={12} />
                          </button>
                        </>
                      ) : (
                        <span
                          className="canvas-placeholder"
                          onClick={(e) => {
                            e.stopPropagation();
                            startEditingConstant(t.field, "");
                          }}
                        >
                          drop a field, or type a value
                        </span>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
