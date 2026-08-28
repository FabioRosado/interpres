import { state } from "./state.js";
import {
  $,
  clear,
  emptyState,
  evidenceStatusClass,
  humanize,
  node,
  pill,
  statusClass,
  stringify,
} from "./dom.js";
import { mappingForUnit } from "./review-index.js";
export function renderEvidenceInspector(target, jumpToDecisionTrail) {
  const content = clear($("#context-sidebar-content"));
  if (!target) {
    content.append(emptyState("Click a Latin unit, annotated phrase, issue, or editorial annotation to inspect it."));
    return;
  }

  const raw = target.raw || {};
  const issueIds = target.issueIds || [];
  const issue = issueIds.length ? (state.view?.issues?.items || []).find((item) => item.issue_id === issueIds[0]) : null;
  const data = issue || raw;
  const selectedUnitId = target.type === "source_unit" ? target.sourceUnitIds?.[0] : (target.sourceUnitIds || [])[0];
  const unit = selectedUnitId ? (state.view?.source?.units || []).find((u) => u.source_unit_id === selectedUnitId) : null;
  const selectedFinalMapping = selectedUnitId ? mappingForUnit(selectedUnitId, state.view?.final?.source_mappings || []) : null;

  function contextSection(summary, bodyContent, open = false) {
    const details = node("details", { className: "context-section", open }, [
      node("summary", { text: summary }),
      node("div", { className: "context-section-body" }),
    ]);
    const body = details.querySelector(".context-section-body");
    if (bodyContent instanceof Node) {
      body.append(bodyContent);
    } else if (Array.isArray(bodyContent)) {
      bodyContent.forEach((child) => { if (child) body.append(child); });
    } else if (typeof bodyContent === "string") {
      body.append(document.createTextNode(bodyContent));
    }
    return details;
  }

  // Source
  const sourceBody = unit ? node("dl", {}, [
    node("dt", { text: "Source unit" }), node("dd", { text: unit.source_unit_id }),
    node("dt", { text: "PL marker" }), node("dd", { text: `PL ${unit.page || "—"}` }),
    node("dt", { text: "Latin" }), node("dd", { text: unit.text || "" }),
  ]) : emptyState("No source unit selected.");
  content.append(contextSection("Source", sourceBody, true));

  // Witnesses
  const witnessNodes = (state.view?.witnesses || []).map((witness) => {
    const isValid = witness.eligible_as_adjudicator_base === true;
    const badge = node("span", { className: `context-badge ${isValid ? "valid-witness" : "invalid-witness"}`, text: isValid ? "VALID WITNESS" : "INVALID WITNESS" });
    const clueNote = witness.authority_role === "non_authoritative_clue_not_evidence" ? node("p", { text: "NON-AUTHORITATIVE CLUE · not machine evidence or corroboration", className: "mapping-note" }) : null;
    const item = node("div", { className: "context-evidence-item" });
    item.append(
      node("div", { className: "context-evidence-header" }, [
        node("b", { text: witness.label }),
        badge,
      ]),
      node("p", { text: `${witness.provider || "provider unrecorded"} · ${witness.model || "model unrecorded"}` }),
    );
    if (witness.available) {
      item.append(node("p", { text: witness.translation || "", className: "latin-quote" }));
    } else {
      item.append(emptyState("No valid witness translation.", witness.state));
    }
    if (clueNote) item.append(clueNote);
    return item;
  });
  content.append(contextSection("Witnesses", witnessNodes, true));

  // Findings
  const allFindings = [
    ...(state.view?.deterministic?.findings || []),
    ...(state.view?.prosecutor?.initial?.findings || []),
    ...(state.view?.prosecutor?.grounded?.findings || []),
    ...(state.view?.adjudicator?.findings || []),
  ];
  const findingNodes = (target.findingIds || []).map((fid) => {
    const finding = allFindings.find((f) => f.finding_id === fid);
    if (!finding) return null;
    const item = node("div", { className: "context-evidence-item" });
    item.append(
      node("div", { className: "context-evidence-header" }, [
        pill(finding.type || "finding"),
        pill(finding.severity || finding.status || "ungraded", `severity-pill ${statusClass(finding.severity || finding.status)}`),
      ]),
      node("p", { text: finding.message || finding.reason || "" }),
    );
    if (finding.latin) item.append(node("p", { text: finding.latin, className: "latin-quote" }));
    return item;
  });
  content.append(contextSection("Findings", findingNodes));

  // Evidence
  const evidenceNodes = (target.evidenceIds || []).map((eid) => {
    const receipt = (state.view?.evidence?.receipts || []).find((r) => r.evidence_id === eid);
    if (!receipt) {
      const item = node("div", { className: "context-evidence-item" });
      item.append(node("p", { text: eid }), emptyState("Receipt not available."));
      return item;
    }
    const grade = receipt.grade || "?";
    const gradeBadge = node("span", { className: `context-badge evidence-grade grade-${String(grade).toLowerCase()}`, text: grade });
    const statusBadge = node("span", { className: `context-badge ${evidenceStatusClass(receipt.status)}`, text: humanize(receipt.status || "UNAVAILABLE").toUpperCase() });
    const request = receipt.request || {};
    const item = node("div", { className: "context-evidence-item" });
    item.append(
      node("div", { className: "context-evidence-header" }, [
        node("b", { text: receipt.evidence_id }),
        gradeBadge,
        statusBadge,
      ]),
    );
    if (request.query) item.append(node("p", { className: "context-evidence-request", text: `Query: ${request.query}` }));
    if (request.reason) item.append(node("p", { className: "context-evidence-request", text: `Reason: ${request.reason}` }));
    (receipt.results || []).forEach((result) => {
      const resultDiv = node("div", { className: "context-evidence-result" });
      resultDiv.append(node("p", { text: result.text || result.match || result.reference || "Result" }));
      if (result.provenance) resultDiv.append(node("pre", { text: stringify(result.provenance) }));
      item.append(resultDiv);
    });
    if (!(receipt.results || []).length) item.append(emptyState("No results."));
    return item;
  });
  content.append(contextSection("Evidence", evidenceNodes));

  // Adjudication
  const adjudicationNodes = [];
  if (state.view?.adjudicator?.base_witness) {
    adjudicationNodes.push(node("div", { className: "context-evidence-item" }, [
      node("dl", {}, [
        node("dt", { text: "Base witness" }),
        node("dd", { text: `Witness ${String(state.view.adjudicator.base_witness).toUpperCase()}` }),
      ]),
    ]));
  }
  (target.editIds || []).forEach((eid) => {
    const edit = (state.view?.adjudicator?.edits || []).find((ed) => ed.edit_id === eid);
    if (!edit) return;
    const item = node("div", { className: "context-evidence-item" });
    item.append(
      node("div", { className: "context-evidence-header" }, [
        node("b", { text: edit.edit_id }),
        pill("edit"),
      ]),
      node("p", { text: `Old: ${edit.old || ""}` }),
      node("p", { text: `New: ${edit.new || ""}` }),
    );
    if (edit.reason) item.append(node("p", { text: edit.reason }));
    adjudicationNodes.push(item);
  });
  if (!adjudicationNodes.length) adjudicationNodes.push(emptyState("No adjudication details for this selection."));
  content.append(contextSection("Adjudication", adjudicationNodes));

  // Final / Editorial
  const finalNodes = [];
  if (state.view?.machine?.final_draft) {
    finalNodes.push(node("div", { className: "context-evidence-item" }, [
      node("dt", { text: "Machine final" }),
      node("dd", { text: state.view.machine.final_draft }),
    ]));
  }
  const humanAnnotation = state.annotations.find((item) => item.annotation_id === target.id);
  if (humanAnnotation) {
    finalNodes.push(node("div", { className: "context-evidence-item" }, [
      node("dt", { text: "Editorial annotation" }),
      node("dd", { text: humanAnnotation.text }),
      node("dt", { text: "Selected text" }),
      node("dd", { text: humanAnnotation.target?.selected_text || "" }),
      node("span", { className: `context-badge ${humanAnnotation.span_status === "stale" ? "stale" : "valid"}`, text: humanAnnotation.span_status === "stale" ? "STALE" : "LINKED" }),
    ]));
  }
  const editorialText = $("#editor-translation").value;
  if (editorialText) {
    finalNodes.push(node("details", { className: "context-evidence-item" }, [
      node("summary", { text: "Current human editorial Markdown" }),
      node("p", { text: editorialText }),
    ]));
  }
  if (selectedFinalMapping) {
    finalNodes.push(node("div", { className: "context-evidence-item" }, [
      node("dt", { text: "Final mapping" }),
      node("dd", { text: `Persisted boundary quotes for ${selectedUnitId}` }),
    ]));
  } else if (selectedUnitId) {
    finalNodes.push(node("div", { className: "context-evidence-item" }, [
      node("dt", { text: "Final mapping" }),
      node("dd", { text: "No persisted final-source mapping for this source unit" }),
    ]));
  }
  if (!finalNodes.length) finalNodes.push(emptyState("No final or editorial data."));
  content.append(contextSection("Final / Editorial", finalNodes, true));

  // Action
  const actionDiv = node("div", { className: "context-action" });
  if (target.decisionTrailId) {
    const trailBtn = node("button", { className: "quiet-button", text: "View in Decision Trail", attrs: { type: "button" } });
    trailBtn.addEventListener("click", () => jumpToDecisionTrail(target.decisionTrailId));
    actionDiv.append(trailBtn);
  }
  content.append(actionDiv);
}
