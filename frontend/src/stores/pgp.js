import { defineStore } from "pinia";
import * as openpgp from "openpgp";
import { clearOwnKeypair, loadOwnKeypair, saveOwnKeypair } from "@/utils/keyStore";

export const usePgpStore = defineStore("pgp", {
  state: () => ({
    loaded: false,
    hasKeypair: false,
    publicKeyArmored: null,
    fingerprint: null,
    // In-memory only for the current session -- never persisted decrypted,
    // never sent anywhere. Cleared on lock()/page reload.
    unlockedPrivateKey: null,
  }),

  getters: {
    isUnlocked: (state) => !!state.unlockedPrivateKey,
  },

  actions: {
    async init() {
      if (this.loaded) return;
      const record = await loadOwnKeypair();
      if (record) {
        this.hasKeypair = true;
        this.publicKeyArmored = record.publicKeyArmored;
        const key = await openpgp.readKey({ armoredKey: record.publicKeyArmored });
        this.fingerprint = key.getFingerprint();
      }
      this.loaded = true;
    },

    async generate({ name, email, passphrase }) {
      const { privateKey, publicKey } = await openpgp.generateKey({
        type: "ecc",
        curve: "curve25519",
        userIDs: [{ name, email }],
        passphrase,
        format: "armored",
      });
      await saveOwnKeypair({ publicKeyArmored: publicKey, encryptedPrivateKeyArmored: privateKey, createdAt: new Date().toISOString() });
      await this._loadFromArmored(publicKey);
    },

    async importKeypair({ publicKeyArmored, privateKeyArmored }) {
      // Validate both parse before persisting anything.
      await openpgp.readKey({ armoredKey: publicKeyArmored });
      const priv = await openpgp.readPrivateKey({ armoredKey: privateKeyArmored });
      if (priv.isDecrypted()) {
        throw new Error("This private key isn't passphrase-protected -- NekoMail requires an encrypted private key for browser storage.");
      }
      await saveOwnKeypair({ publicKeyArmored, encryptedPrivateKeyArmored: privateKeyArmored, createdAt: new Date().toISOString() });
      await this._loadFromArmored(publicKeyArmored);
    },

    async _loadFromArmored(publicKeyArmored) {
      this.hasKeypair = true;
      this.publicKeyArmored = publicKeyArmored;
      const key = await openpgp.readKey({ armoredKey: publicKeyArmored });
      this.fingerprint = key.getFingerprint();
      this.loaded = true;
    },

    async unlock(passphrase) {
      const record = await loadOwnKeypair();
      if (!record) throw new Error("No PGP key set up yet");
      const encryptedKey = await openpgp.readPrivateKey({ armoredKey: record.encryptedPrivateKeyArmored });
      this.unlockedPrivateKey = await openpgp.decryptKey({ privateKey: encryptedKey, passphrase });
    },

    lock() {
      this.unlockedPrivateKey = null;
    },

    async deleteKeypair() {
      await clearOwnKeypair();
      this.hasKeypair = false;
      this.publicKeyArmored = null;
      this.fingerprint = null;
      this.unlockedPrivateKey = null;
    },

    async exportRecord() {
      return loadOwnKeypair();
    },
  },
});
