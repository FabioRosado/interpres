import type { SelectionTarget } from '../../app/types';
import type { AnnotationRecord } from '../../app/types';
import { annotationRange } from '../../lib/annotations';
import { useRef, useEffect } from 'preact/hooks';

interface Props {
  text: string;
  annotations: AnnotationRecord[];
  options?: { preferReplacement?: boolean; editorial?: boolean };
  selectedTarget?: SelectionTarget | null;
  layers?: Record<string, boolean>;
  onSelect?: (target: SelectionTarget) => void;
}

export const AnnotatedText = ({ text, annotations, options, selectedTarget, layers = {}, onSelect }: Props) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const source = String(text || '');
    const ranges: { start: number; end: number; annotation: AnnotationRecord; nested: AnnotationRecord[] }[] = [];
    const used = new Set<string>();

    for (const annotation of annotations) {
      if (!layers[annotation.layer] && !targetMatchesAnnotation(selectedTarget, annotation)) continue;
      const range = annotationRange(source, annotation as unknown as Record<string, unknown>, options);
      if (!range) continue;
      const key = `${range.start}:${range.end}:${annotation.id}`;
      if (used.has(key)) continue;
      used.add(key);
      ranges.push({ ...range, annotation, nested: [] });
    }

    ranges.sort((a, b) => a.start - b.start || b.end - a.end);
    const filtered: { start: number; end: number; annotation: AnnotationRecord; nested: AnnotationRecord[] }[] = [];
    let cursor = -1;
    for (const range of ranges) {
      if (range.start < cursor) {
        const existing = filtered.find((item) => item.start <= range.start && item.end >= range.end);
        if (existing) existing.nested.push(range.annotation);
        continue;
      }
      filtered.push({ ...range, nested: [] });
      cursor = range.end;
    }

    container.replaceChildren();
    let offset = 0;
    for (const range of filtered) {
      if (range.start > offset) container.appendChild(document.createTextNode(source.slice(offset, range.start)));
      const allAnnotations = [range.annotation, ...range.nested];
      const selectedAnnotation = allAnnotations.find((annotation) => targetMatchesAnnotation(selectedTarget, annotation));
      const primary = selectedAnnotation || range.annotation;
      const marker = allAnnotations.length > 1 ? String(allAnnotations.length) : primary.layer.slice(0, 1);
      const isSelected = Boolean(selectedAnnotation);
      const isHiddenLayer = !layers[primary.layer] && !isSelected;

      const span = document.createElement('span');
      span.className = `annotation ${primary.layer} ${isHiddenLayer ? 'hidden-layer' : ''} ${isSelected ? 'selected selected-source' : ''}`.trim();
      span.title = allAnnotations.map((a) => a.label || humanize(a.layer)).join('\n');
      span.dataset.reviewId = primary.id;
      span.dataset.marker = marker;
      span.setAttribute('tabindex', '0');
      span.setAttribute('role', 'button');
      span.setAttribute('aria-label', `Review annotation: ${primary.label || primary.layer}`);
      span.textContent = source.slice(range.start, range.end);

      span.addEventListener('click', (e) => {
        e.stopPropagation();
        onSelect?.(targetFromAnnotation(primary) as SelectionTarget);
      });
      span.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect?.(targetFromAnnotation(primary) as SelectionTarget);
        }
      });

      container.appendChild(span);
      offset = range.end;
    }
    if (offset < source.length) container.appendChild(document.createTextNode(source.slice(offset)));
    if (!source) container.appendChild(emptyState('No text is available.'));
    window.requestAnimationFrame(() => {
      container.querySelector<HTMLElement>('.annotation.selected')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }, [text, annotations, options, selectedTarget, layers, onSelect]);

  return <div ref={containerRef} className="annotated-text" />;
};

function targetMatchesAnnotation(target: SelectionTarget | null | undefined, annotation: AnnotationRecord | null | undefined): boolean {
  if (!target || !annotation) return false;
  if (target.type === 'source_unit') {
    return annotation.type === 'source_mapping' && containsAny(target.sourceUnitIds, annotation.sourceUnitIds);
  }
  return target.id === annotation.id
    || containsAny(target.sourceUnitIds, annotation.sourceUnitIds)
    || containsAny(target.issueIds, annotation.issueIds)
    || containsAny(target.findingIds, annotation.findingIds)
    || containsAny(target.evidenceIds, annotation.evidenceIds)
    || containsAny(target.editIds, annotation.editIds);
}

function targetFromAnnotation(annotation: AnnotationRecord) {
  return {
    id: annotation.id,
    type: annotation.type,
    sourceUnitIds: annotation.sourceUnitIds,
    findingIds: annotation.findingIds,
    evidenceIds: annotation.evidenceIds,
    editIds: annotation.editIds,
    issueIds: annotation.issueIds,
    decisionTrailId: annotation.decisionTrailId,
    label: annotation.label || '',
    raw: annotation.raw,
  };
}

function containsAny(left: string[] | undefined, right: string[] | undefined): boolean {
  const rightSet = new Set(right || []);
  return (left || []).some((item) => rightSet.has(item));
}

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function emptyState(message: string) {
  const div = document.createElement('div');
  div.className = 'empty-state';
  div.textContent = message;
  return div;
}
