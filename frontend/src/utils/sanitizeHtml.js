import DOMPurify from "dompurify";

// Rendered inside a sandboxed <iframe srcdoc> with no allow-scripts, so
// inline <style>/style="" (very common in real HTML mail) is safe to keep --
// the sandbox is what actually blocks script execution, not attribute
// stripping. Still drop <base>, which could otherwise redirect relative
// resource/link resolution out from under the sandboxed document.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

export function sanitizeEmailHtml(html) {
  if (!html) return "";
  return DOMPurify.sanitize(html, { FORBID_TAGS: ["base"] });
}

// Rewrites inline-image `src="cid:..."` references (very common in real
// mail) to the attachment-download endpoint, using the MessageDetail's
// already-loaded attachments list. Content-ID headers are stored with their
// surrounding angle brackets (e.g. "<abc123@mail>"), cid: URLs are not.
export function rewriteCidLinks(html, messageId, attachments) {
  if (!html || !attachments?.length) return html;

  const byContentId = new Map();
  for (const att of attachments) {
    if (att.content_id) {
      byContentId.set(att.content_id.replace(/^<|>$/g, ""), att.id);
    }
  }
  if (byContentId.size === 0) return html;

  return html.replace(/src=(["'])cid:([^"']+)\1/gi, (match, quote, cid) => {
    const attachmentId = byContentId.get(cid);
    if (attachmentId == null) return match;
    return `src=${quote}/api/messages/${messageId}/attachments/${attachmentId}${quote}`;
  });
}
