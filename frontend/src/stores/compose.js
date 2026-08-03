import { defineStore } from "pinia";
import { useAccountsStore } from "@/stores/accounts";

function addrToString(a) {
  if (!a) return "";
  return a.name ? `${a.name} <${a.email}>` : a.email;
}
function addrListToString(addrs) {
  return (addrs || []).map(addrToString).join(", ");
}
function quoteBody(message) {
  const dateStr = message.date ? new Date(message.date).toLocaleString() : "";
  const fromLabel = addrToString(message.from_addrs?.[0]);
  const quoted = (message.body_text || "").split("\n").map((l) => `> ${l}`).join("\n");
  return `\n\nOn ${dateStr}, ${fromLabel} wrote:\n${quoted}`;
}
function blankDraft(accountId) {
  return {
    accountId, to: "", cc: "", bcc: "", subject: "", bodyText: "",
    inReplyToMessageId: null, draftId: null, attachments: [], hadServerAttachments: false,
  };
}

export const useComposeStore = defineStore("compose", {
  state: () => ({
    open: false,
    draft: null,
  }),
  actions: {
    openNew(accountId) {
      this.draft = blankDraft(accountId);
      this.open = true;
    },
    openReply(message, mode) {
      const from = message.from_addrs?.[0];
      let cc = "";
      if (mode === "reply_all") {
        const accounts = useAccountsStore();
        const selfEmail = accounts.items.find((a) => a.id === message.account_id)?.email_address?.toLowerCase();
        const rest = [...(message.to_addrs || []), ...(message.cc_addrs || [])].filter(
          (a) => a.email.toLowerCase() !== selfEmail && a.email.toLowerCase() !== from?.email?.toLowerCase(),
        );
        cc = addrListToString(rest);
      }
      const subject = message.subject && /^re:/i.test(message.subject) ? message.subject : `Re: ${message.subject || ""}`;
      this.draft = {
        ...blankDraft(message.account_id),
        to: addrToString(from),
        cc,
        subject,
        bodyText: quoteBody(message),
        inReplyToMessageId: message.id,
      };
      this.open = true;
    },
    openForward(message) {
      const subject = message.subject && /^fwd:/i.test(message.subject) ? message.subject : `Fwd: ${message.subject || ""}`;
      this.draft = {
        ...blankDraft(message.account_id),
        subject,
        bodyText: quoteBody(message),
      };
      this.open = true;
    },
    openDraft(message) {
      this.draft = {
        ...blankDraft(message.account_id),
        to: addrListToString(message.to_addrs),
        cc: addrListToString(message.cc_addrs),
        bcc: addrListToString(message.bcc_addrs),
        subject: message.subject || "",
        bodyText: message.body_text || "",
        draftId: message.id,
        hadServerAttachments: message.has_attachments,
      };
      this.open = true;
    },
    close() {
      this.open = false;
      this.draft = null;
    },
  },
});
