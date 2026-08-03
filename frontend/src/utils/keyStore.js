// Stores the user's own PGP keypair in the browser's IndexedDB -- per
// device, never synced to the server (see stores/pgp.js and NEXT_STEPS.md
// Phase 9). The private key is always stored passphrase-encrypted (armored
// text straight out of openpgp.generateKey/decryptKey's counterpart); this
// module never sees or handles a decrypted private key, only opaque strings.

const DB_NAME = "nekomail-pgp";
const DB_VERSION = 1;
const STORE = "keys";
const OWN_KEY = "own-keypair";

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withStore(mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const store = tx.objectStore(STORE);
    let result;
    Promise.resolve(fn(store))
      .then((r) => { result = r; })
      .catch(reject);
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
  });
}

function reqToPromise(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

// record shape: { publicKeyArmored: string, encryptedPrivateKeyArmored: string, createdAt: string }
export function loadOwnKeypair() {
  return withStore("readonly", (store) => reqToPromise(store.get(OWN_KEY)));
}

export function saveOwnKeypair(record) {
  return withStore("readwrite", (store) => reqToPromise(store.put(record, OWN_KEY)));
}

export function clearOwnKeypair() {
  return withStore("readwrite", (store) => reqToPromise(store.delete(OWN_KEY)));
}
