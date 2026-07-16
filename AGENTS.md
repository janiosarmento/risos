# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Sempre peça esclarecimentos quando o pedido do usuário não for suficientemente claro; não faça suposições.

- Use `bd` para ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Regenerate static HTML** (if front-end changed) - Run `cd backend && python -m app.html_assembler` to sync `index.html` and `manifest.json` from `index.template.html`
4. **Update issue status** - Close finished work, update in-progress items
5. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
6. **Clean up** - Clear stashes, prune remote branches
7. **Verify** - All changes committed AND pushed
8. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
Use 'bd' for task tracking


<claude-mem-context>
# Memory Context

# [risos] recent context, 2026-07-15 7:25am GMT-3

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (15,717t read) | 508,716t work | 97% savings

### Jul 1, 2026
2314 9:17p 🔵 S11 verified: tests passing, linting clean, ready for commit
2315 " ✅ S11 completed and shipped: URL safety guards added to feed and article fetches
2330 9:34p 🔵 Investigated posts endpoint category filtering logic
2331 " 🔵 Frontend correctly sends category_id parameter to posts endpoint
2332 " 🔵 Located frontend posts API call with query parameters
2333 " 🔵 Frontend loadPosts function implements complete filter composition logic
2334 9:35p 🔵 Backend _apply_post_filters function handles category_id filtering
2335 " 🔵 Database schema mismatch: posts table missing skip_summary column
2336 9:46p 🔵 Database schema mismatch: ORM references non-existent posts.skip_summary column
2337 " 🔴 Undefined variable in category filter logic
2338 9:48p 🔄 Fix undefined variable bug by returning filter dimensions from helper function
2339 " 🔴 Complete undefined variable fix by unpacking returned filter dimensions in caller
2340 " 🔴 Category and topic filters now work end-to-end
2341 9:49p 🔴 Test suite passes after undefined variable fix
2342 " ✅ Undefined variable fix committed and pushed to main
2343 " 🔄 Expand abbreviation pattern to recognize single-letter abbreviations
2344 9:50p 🔵 Paragraph splitting correctly handles single-letter initials and abbreviations
2345 9:51p 🔵 All tests pass after abbreviation pattern expansion
2346 " ✅ Single-letter initial abbreviation fix committed and pushed
2347 9:52p 🔄 Refactor update_preferences to data-driven loop pattern (K4)
2348 9:54p 🔵 K4 refactor verified: all tests pass with clean linting
2349 " 🔵 K4 refactor verified end-to-end: all field types update correctly
2350 9:55p ✅ K4 refactor committed and pushed: data-driven preference update loops
2351 " 🔵 Single-letter abbreviation pattern verified working with real user examples
2352 9:57p 🔵 Paragraph splitting fix confirmed working: both single-letter initials handled correctly
2353 10:19p 🔵 Tag merge suggestion algorithm with specialized indexing and heuristics
2354 10:20p 🔵 LLM-guided tag merge validation with version number protection
2355 " 🔄 Extract tag indexing and LLM prompt logic into reusable helper functions
2356 " 🔵 Incomplete refactoring: segment_to_tags missing from _build_tag_indexes return dict
2357 " 🔄 Replaced inline index building with call to _build_tag_indexes helper (incomplete)
2358 10:21p 🔄 Completed K3 refactoring: _build_tag_indexes helper function added and integrated
2359 " ✅ K3 refactoring verified: all tests pass, no linting errors
2360 " ✅ K3 refactoring committed and pushed to main branch
2361 10:23p 🔵 Frontend template structure: two post-reader templates with significant code duplication
2362 " 🔵 Template composition via HTML assembler with <!-- INCLUDE path --> directives
2363 10:24p ✅ REFACTOR.md updated: K7 marked as partially resolved
2364 " ✅ REFACTOR.md updated: K11 and D5 marked as paused, architectural constraints documented
2365 10:25p ✅ REFACTOR.md updated: D6 marked as paused, cross-language duplication accepted as technical debt
2366 " ✅ REFACTOR.md finalized: Phase 5 (KISS backend) completed, 22/33 items done (67%), all high/medium severity resolved
### Jul 12, 2026
S2061 Add sidebar toggle/hide feature to Risos app for desktop - feasibility assessment and implementation planning (Jul 12 at 10:38 PM)
3789 10:39p 🔵 Sidebar toggle state already fully implemented in Alpine.js
S2062 Implement desktop sidebar toggle for Risos RSS app — allow users to hide/show sidebar on demand on desktop while preserving existing mobile swipe toggle (Jul 12 at 10:39 PM)
3790 " ✅ Begin implementation of desktop sidebar toggle feature with localStorage persistence
S2063 Implement desktop sidebar hide/show toggle for Risos RSS app and commit feature to repository (Jul 12 at 10:42 PM)
S2064 Push code changes to remote repository (risos project) (Jul 12 at 10:44 PM)
S2065 Push code changes to remote repository and close out session (risos project) (Jul 12 at 10:49 PM)
S2066 Implement sidebar hide/show toggle feature for Risos app and close out session (Jul 12 at 10:50 PM)
3796 10:52p 🔵 Local backend setup blocked by editable path dependencies
S2111 Fix paragraph break function incorrectly splitting after "Mr." in "Mr. Meeseeks" (Jul 12 at 10:52 PM)
### Jul 13, 2026
3910 9:50p 🔵 Paragraph break function missing "Mr." in abbreviations list
3911 9:51p 🔵 Abbreviations list missing English titles (Mr., Mrs., Ms., Miss)
3912 " 🔴 Added missing English name titles to abbreviations list
S2112 Fix paragraph break function incorrectly splitting "Mr. Meeseeks" after "Mr." — identify root cause, implement fix, test, and commit changes (Jul 13 at 9:51 PM)
3913 9:52p 🔵 APP_VERSION configuration located in front-end templates
3914 " ✅ APP_VERSION bumped to 20260713a
3915 " 🔵 HTML assembler successfully compiled front-end with new version
3916 9:53p ✅ Changes committed to main branch
S2113 Configure git workflow to automatically push after commits without asking for confirmation in risos project (Jul 13 at 9:53 PM)
3917 10:01p ⚖️ Automatic push after commits in risos project
S2114 Justify and reinforce automatic push-after-commit workflow for risos project based on risk analysis of normal (non-force) git pushes (Jul 13 at 10:02 PM)
**Investigated**: Examined safety implications of automatic push in solo project context versus collaborative/CI scenarios. Analyzed reversibility of normal pushes versus force-pushes and their impact on project history and team collaboration.

**Learned**: Normal (fast-forward) pushes carry low risk and are highly reversible in solo projects without coupled CI. Undoing requires either `git revert` (new commit) or `git push --force` to prior state if no other collaborators have pulled yet. Force-pushes (which rewrite remote history) pose real risks in multi-contributor or CI-coupled environments, but are safe in solo projects. The generic instinct to request push confirmation was overly cautious for risos's actual context (solo development, no auto-pulling CI). Normal push safety profile approximates local commits in this specific project configuration.

**Completed**: Reinforced and validated the automatic push-after-commit workflow preference. Confirmed memory setting remains in place for risos project. Decision rationale documented with risk/reversibility analysis specific to solo project context.

**Next Steps**: Workflow preference active and justified. No additional configuration needed; automatic push will continue for commits in risos going forward.


Access 509k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>