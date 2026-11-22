## Summary
<!-- What changes for the person using the app, in plain sentences. -->

Closes #

## Type of change
<!-- Tick one, and set the matching label. The Version label check needs exactly one. -->
- [ ] `semver:minor`: new feature, or `SCHEMA_VERSION` bumped
- [ ] `semver:patch`: fix or tuning
- [ ] `semver:none`: docs, tests or CI only
- [ ] Also `breaking`: an existing workspace, command or setting stops working

## Try it
<!-- How to run a PR: README, "Review a pull request". Keep the next two lines. -->
Rebuild the analysis first: <!-- "Update now" if SCHEMA_VERSION changed; "Demos tab, Apply" if the output changes without a bump; otherwise "not needed". -->
Changes or deletes data: <!-- yes (say which steps), or no. -->

<!-- Which tab or page to open, what to click, what to look for. If there is nothing to see in the app, say so in one line. -->

## Testing
- [ ] G-fast
- [ ] G-browser
- [ ] G-demos (real demos, local only)

Not tested, and why:

## Safety
- [ ] No real team names, nicknames or SteamIDs (code, tests, docs, this text)
- [ ] No demos or `tests/local_fixtures/` files
- [ ] The API key is never logged, printed or exported

## If findings or round stories changed
- [ ] `SCHEMA_VERSION` bumped in `core/findings.py`
- [ ] Docs updated (requirements, target-design "Changed" note)

## Screenshots
<!-- UI changes only. Use synthetic data. -->
