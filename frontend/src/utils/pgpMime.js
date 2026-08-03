// Client-side PGP/MIME (RFC 3156) construction and decryption, using
// openpgp.js. Everything in this file runs in the browser -- the whole
// point of Phase 9 is that NekoMail's backend never sees plaintext for an
// encrypted message, only the already-encrypted bytes it relays as-is
// (see services/mail/compose.py's raw_mime path).
//
// v1 scope (deliberately bounded, see NEXT_STEPS.md Phase 9): combined
// encrypt+sign in one PGP/MIME `multipart/encrypted` message. No
// sign-only `multipart/signed` mode, no Bcc on encrypted sends (Bcc
// recipients would need their own separately-encrypted copy, which this
// version doesn't build). Reading side handles the two inner-entity shapes
// NekoMail itself produces (plain text, or multipart/mixed with
// attachments) plus a plain-text fallback for anything else.
import * as openpgp from "openpgp";

function crlf(text) {
  return text.replace(/\r\n/g, "\n").replace(/\n/g, "\r\n");
}

function boundary() {
  return `nekomail-${crypto.randomUUID()}`;
}

function base64Wrap(b64) {
  return b64.replace(/(.{76})/g, "$1\r\n");
}

function buildInnerEntity({ bodyText, attachments }) {
  const textPart = `Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n${crlf(bodyText || "")}`;
  if (!attachments || !attachments.length) {
    return textPart;
  }

  const bound = boundary();
  const attachmentParts = attachments.map(
    (a) =>
      `Content-Type: ${a.mimeType || "application/octet-stream"}; name="${a.filename}"\r\n` +
      `Content-Transfer-Encoding: base64\r\n` +
      `Content-Disposition: attachment; filename="${a.filename}"\r\n\r\n` +
      `${base64Wrap(a.dataBase64)}`,
  );
  const body = [textPart, ...attachmentParts].map((p) => `--${bound}\r\n${p}`).join("\r\n") + `\r\n--${bound}--`;
  return `Content-Type: multipart/mixed; boundary="${bound}"\r\n\r\n${body}`;
}

async function fileToBase64(file) {
  const buf = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

/**
 * Builds a complete, ready-to-send PGP/MIME message (RFC 3156
 * multipart/encrypted): encrypts a self-contained inner MIME entity
 * (text + attachments) to every recipient's public key AND the sender's
 * own public key (encrypt-to-self -- otherwise the sender's own Sent copy
 * would be unreadable by them), optionally signs with the sender's
 * unlocked private key, then wraps the result in the outer envelope with
 * plaintext routing headers (From/To/Subject/etc. -- PGP/MIME never
 * encrypts these, which is exactly why search over encrypted mail stays
 * subject/sender only).
 */
export async function buildEncryptedMime({
  fromEmail, fromName, to, cc, subject, messageId, inReplyTo, references,
  bodyText, attachments, recipientPublicKeys, ownPublicKeyArmored, signingPrivateKey,
}) {
  const fileAttachments = await Promise.all(
    (attachments || []).map(async (f) => ({ filename: f.name, mimeType: f.type, dataBase64: await fileToBase64(f) })),
  );
  const innerEntity = buildInnerEntity({ bodyText, attachments: fileAttachments });

  const ownPublicKey = await openpgp.readKey({ armoredKey: ownPublicKeyArmored });
  const encryptionKeys = [...recipientPublicKeys, ownPublicKey];

  const message = await openpgp.createMessage({ text: innerEntity });
  const encrypted = await openpgp.encrypt({
    message,
    encryptionKeys,
    signingKeys: signingPrivateKey ? [signingPrivateKey] : undefined,
    format: "armored",
  });

  const bound = boundary();
  const from = fromName ? `"${fromName.replace(/"/g, "")}" <${fromEmail}>` : fromEmail;
  const headerLines = [
    `From: ${from}`,
    to && to.trim() ? `To: ${to}` : null,
    cc && cc.trim() ? `Cc: ${cc}` : null,
    `Subject: ${subject || ""}`,
    `Date: ${new Date().toUTCString().replace("GMT", "+0000")}`,
    `Message-ID: ${messageId}`,
    inReplyTo ? `In-Reply-To: ${inReplyTo}` : null,
    references ? `References: ${references}` : null,
    "MIME-Version: 1.0",
    `Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="${bound}"`,
  ].filter(Boolean);

  const body =
    `--${bound}\r\n` +
    `Content-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n\r\n` +
    `--${bound}\r\n` +
    `Content-Type: application/octet-stream; name="encrypted.asc"\r\n\r\n${encrypted}\r\n` +
    `--${bound}--\r\n`;

  return `${headerLines.join("\r\n")}\r\n\r\n${body}`;
}

/** Naive one-level MIME splitter for the inner entity we (or another
 * PGP/MIME-producing client) decrypt back out -- deliberately not a full
 * MIME parser (see module docstring for the bounded v1 scope).
 *
 * openpgp.decrypt()'s default `format: 'utf8'` normalizes all line endings
 * to bare `\n` (that's the documented behavior, not a bug) -- this parser
 * works entirely in `\n`-normalized space throughout for exactly that
 * reason, even though the entity was originally built with `\r\n` for real
 * MIME/SMTP transport (see buildInnerEntity above). */
function splitMultipart(rawText) {
  const text = rawText.replace(/\r\n/g, "\n");
  const ctMatch = text.match(/^Content-Type:\s*([^\n;]+)(.*)$/im);
  if (!ctMatch) return { contentType: "text/plain", body: text };
  const contentType = ctMatch[1].trim().toLowerCase();
  const boundMatch = ctMatch[2].match(/boundary="?([^";\n]+)"?/i);

  if (contentType !== "multipart/mixed" || !boundMatch) {
    const headerEnd = text.indexOf("\n\n");
    return { contentType, body: headerEnd === -1 ? text : text.slice(headerEnd + 2) };
  }

  const bound = boundMatch[1];
  const rawParts = text.split(`--${bound}`).slice(1, -1);
  const parts = rawParts.map((raw) => {
    const cleaned = raw.replace(/^\n/, "");
    const headerEnd = cleaned.indexOf("\n\n");
    const headerBlock = headerEnd === -1 ? cleaned : cleaned.slice(0, headerEnd);
    const partBody = headerEnd === -1 ? "" : cleaned.slice(headerEnd + 2);
    const partCt = (headerBlock.match(/Content-Type:\s*([^\n;]+)/i) || [, "text/plain"])[1].trim().toLowerCase();
    const filenameMatch = headerBlock.match(/(?:filename|name)="?([^";\n]+)"?/i);
    const isBase64 = /Content-Transfer-Encoding:\s*base64/i.test(headerBlock);
    return { contentType: partCt, filename: filenameMatch ? filenameMatch[1] : null, body: partBody, isBase64 };
  });
  return { contentType: "multipart/mixed", parts };
}

/**
 * Decrypts (and verifies, if the sender's public key is known) an armored
 * PGP message, then does a best-effort split of the resulting inner MIME
 * entity into a text body plus any attachments. Returns
 * { bodyText, attachments: [{filename, mimeType, blob}], verified: true|false|null }
 * (`verified` is null when no sender public key was supplied to check against).
 */
export async function decryptPgpMessage({ armoredCiphertext, privateKey, senderPublicKeyArmored }) {
  const message = await openpgp.readMessage({ armoredMessage: armoredCiphertext });
  const verificationKeys = senderPublicKeyArmored ? [await openpgp.readKey({ armoredKey: senderPublicKeyArmored })] : undefined;

  const { data, signatures } = await openpgp.decrypt({
    message,
    decryptionKeys: privateKey,
    verificationKeys,
    expectSigned: false,
  });

  let verified = null;
  if (verificationKeys && signatures.length) {
    try {
      await signatures[0].verified;
      verified = true;
    } catch {
      verified = false;
    }
  }

  const split = splitMultipart(data);
  if (split.contentType !== "multipart/mixed") {
    return { bodyText: split.body.trim(), attachments: [], verified };
  }

  const textPart = split.parts.find((p) => p.contentType === "text/plain");
  const attachmentParts = split.parts.filter((p) => p !== textPart);
  const attachments = attachmentParts.map((p) => {
    const binary = p.isBase64 ? atob(p.body.replace(/\r?\n/g, "")) : p.body;
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return { filename: p.filename || "attachment", mimeType: p.contentType, blob: new Blob([bytes], { type: p.contentType }) };
  });

  return { bodyText: (textPart?.body || "").trim(), attachments, verified };
}
