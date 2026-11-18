# Agent Git Workflow

By default you should never do this. Unless the user allows it.

## Work on a local branch

1. An explicit request to make changes authorizes creating a local feature branch from `main`, staging the changes for that task, and committing them locally. Answer questions and review-only requests without creating a branch.
2. Check `git status --short --branch` before editing. Use `git switch -c <branch> main` in a clean checkout. If the checkout has unrelated work, use a separate Git worktree based on `main` to preserve the user's changes and staging area. Make task commits on the feature branch.
3. For substantial changes, aim to split the work into focused commits that can be reviewed independently. Keep each change with its relevant tests. A single commit is fine for small or tightly coupled changes.
4. Review the staged diff before each commit. Include only changes that belong to the task and follow the repository's verification rules.

## Credit the agent in commit messages

Keep the user's configured Git author. For each commit an agent helped write, add a `Co-authored-by` trailer after a blank line at the end of the commit message. Use the contributing agent's name and a verified GitHub-linked email for that identity. Add a separate trailer for each contributing agent. [GitHub co-author documentation](https://docs.github.com/en/pull-requests/how-tos/commit-changes/creating-a-commit-with-multiple-authors)

```text
Co-authored-by: Agent Name <verified GitHub-linked email>
```

Use this verified trailer for Codex contributions. [Codex GitHub account](https://github.com/codex)

```text
Co-authored-by: Codex <267193182+codex@users.noreply.github.com>
```

Use this verified trailer for GitHub Copilot contributions. [GitHub Copilot documentation](https://docs.github.com/en/copilot)

```text
Co-authored-by: Copilot <copilot@github.com>
```

Use this verified trailer for Gemini contributions. [Gemini Code Assist GitHub App](https://github.com/apps/gemini-code-assist)

```text
Co-authored-by: gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>
```

Use this verified trailer for CodeRabbit contributions. [CodeRabbit GitHub App](https://github.com/apps/coderabbitai)

```text
Co-authored-by: coderabbitai[bot] <136622811+coderabbitai[bot]@users.noreply.github.com>
```

If you cannot verify the agent's email, record the credit with a plain-text trailer such as `Assisted-by: Agent Name`.

## Ask before publishing

1. Share the local branch name, a summary of the changes, the verification results, and the proposed pull request title and description.
2. Wait for explicit user approval to publish. Keep the branch local until approval covers both pushing the branch and opening the pull request, including a draft.
3. After approval, push the feature branch, open the pull request against `main`, and share its link. Merging requires separate approval. [GitHub CLI pull request documentation](https://cli.github.com/manual/gh_pr_create)

## Load the shared instructions

Codex reads `AGENTS.md` directly, and this repository's `CLAUDE.md` directs Claude Code to it. For Gemini CLI, import the same instructions with `@./AGENTS.md` in a root `GEMINI.md`, or configure `context.fileName` to load `AGENTS.md`. [Codex repository instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md) · [Gemini CLI context files](https://geminicli.com/docs/cli/gemini-md/)
