# The Volumax vault (`.volumax`) — "Owner-or-Nothing"

Choose **Volumax Vault (.volumax)** in *Create*. Everything on this page applies **only** to that format.
Other formats (7z, zip, ...) are untouched.

## What it does
- **Recognised by signature, not extension.** A vault renamed to `.jpg` still opens in Volumax; ZIP, PDF and random
  files are rejected immediately. To anyone else the file is random noise.
- **Encryption:** libsodium (via PyNaCl). Argon2id (256 MiB, 3 passes by default) derives the key; a random per-vault
  data key is wrapped in the header; the payload is XChaCha20-Poly1305 (secretstream). One flipped bit makes
  unlocking/extracting fail cleanly. No home-made cipher.
- **Unlock methods:** PIN, Passphrase, Key document, Passphrase + key document, PIN + key document. Nothing about the
  method is stored in the file; the Unlock screen starts blank and a wrong choice counts as a failed attempt.
  The key document is only ever hashed, byte-exact; it is never stored.
- **Self-destruct (opt-in per vault):** after N failed attempts the header region holding the wrapped key is
  overwritten with random bytes (cryptographic erasure), optionally deleting the file. The counter lives outside the
  vault, in an encrypted local database keyed by the vault's random ID, so restoring an old copy on the same PC does not
  reset it, and every copy is erased when opened there once the limit is spent.
- **Duress password (optional):** a second secret that opens a harmless decoy, or silently triggers the wipe.
- **Memory hygiene:** keys and plaintext buffers are zeroed after use, core dumps are disabled, no plaintext temp files.
- **Audit log:** encrypted, hash-chained (tampering is detectable), records success/failure/time. Local only.
- **First launch:** you accept the no-recovery contract once; it is logged and not repeated.

## The contract
Volumax cannot recover a file you lose, forget or break. There is no reset, no backdoor, no support ticket.
If you lose the key, the data is gone.

## Honest limits (please read)
No software can promise "cannot be cracked or bypassed" or that "every copy dies":
1. **The attempt limit only stops people using the Volumax app.** Someone who copies the file can guess offline, with
   no counter at all. Their only obstacle is Argon2id and **how strong your secret is.** A 4-digit PIN falls quickly;
   use a long passphrase and/or a key document.
2. **Copies made before a wipe keep their header** and stay openable with the right secret. Erasure acts on the copy
   that Volumax opens on a PC that knows the vault's ID.
3. **SSDs and journaling file systems** (wear levelling, snapshots, backups, shadow copies) may keep old blocks after
   an overwrite.
4. **Memory zeroing in Python is best-effort;** copies may exist that the runtime made internally.
5. **The container design is custom and unaudited.** The primitives are standard; the assembly has not had independent
   review. For high-stakes secrets, get one.
6. Malware on your PC (keyloggers) beats any file encryption.

## Files
`src/volumax/vault.py` (format), `vault_store.py` (counters, audit log), `ui/vault_dialogs.py` (screens),
`tests/test_vault.py`.
