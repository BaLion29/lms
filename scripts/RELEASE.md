# Release checklist

Manual steps for the maintainer. Run `scripts/validate-release.sh` before
each step marked with [✓].

1. **Rotate the leaked LiteLLM API key.** A key matching
   `sk-[A-Za-z0-9]{16,}` exists in git history. Revoke it, generate a new one,
   and `export LITELLM_API_KEY=sk-...`. [✓]

2. **Review the diff:** `git status && git diff`.

3. **Validate:** `bash scripts/validate-release.sh` — must exit 0. [✓]

4. **Commit:**
   ```
   git add -A
   git commit -m "chore(release): rename lms -> firnline, cleanup, docs, v0.1.0-alpha prep"
   ```

5. **Tag:** `git tag -a v0.1.0-alpha -m "firnline v0.1.0-alpha"`.

6. **Push (optional):** Recreate the GitHub remote (old:
   `git@github.com:BaLion29/lms.git`):
   ```
   git remote remove origin
   git remote add origin git@github.com:BaLion29/firnline.git
   git push origin main --tags
   ```

7. **Deep-clean note:** The leaked key remains in git history; rotating it
   (step 1) is mandatory, history rewrite optional.
