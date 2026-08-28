export function textDiff(before: string, after: string): { kind: string; text: string }[] {
  const beforeParts = String(before || '').split(/(\s+)/);
  const afterParts = String(after || '').split(/(\s+)/);
  if (!before && !after) return [];
  const matrix: number[][] = Array.from({ length: beforeParts.length + 1 }, () => Array(afterParts.length + 1).fill(0));
  for (let i = 1; i <= beforeParts.length; i++) {
    for (let j = 1; j <= afterParts.length; j++) {
      matrix[i][j] = beforeParts[i - 1] === afterParts[j - 1]
        ? matrix[i - 1][j - 1] + 1
        : Math.max(matrix[i][j - 1], matrix[i - 1][j]);
    }
  }
  const ops: { kind: string; text: string }[] = [];
  let i = beforeParts.length;
  let j = afterParts.length;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && beforeParts[i - 1] === afterParts[j - 1]) {
      ops.unshift({ kind: 'equal', text: beforeParts[--i] });
      j--;
    } else if (j > 0 && (i === 0 || matrix[i][j - 1] >= matrix[i - 1][j])) {
      ops.unshift({ kind: 'insert', text: afterParts[--j] });
    } else {
      ops.unshift({ kind: 'delete', text: beforeParts[--i] });
    }
  }
  return ops.reduce((segments, op) => {
    if (!op.text) return segments;
    const previous = segments.at(-1);
    if (previous?.kind === op.kind) previous.text += op.text;
    else segments.push({ ...op });
    return segments;
  }, [] as { kind: string; text: string }[]);
}

export function reviewLinksPersisted(view: Record<string, unknown>): Record<string, unknown> {
  return (view.review_links as { persisted?: Record<string, unknown> } | undefined)?.persisted || {};
}

export function reviewLinksUnavailable(view: Record<string, unknown>): Record<string, boolean> {
  return (view.review_links as { unavailable?: Record<string, boolean> } | undefined)?.unavailable || {};
}