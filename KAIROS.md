# Kairos fork of ContextForge

This is Kairos's fork of [IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge).
It carries the patches the Kairos connector needs until upstream releases them.
The default branch is `kairos/<upstream version>`: an upstream release tag plus
one commit per patch. Releases are tagged `<upstream version>-kairos.<n>`.

The connector image (`kairos-ai-global/kairos-connector`,
`images/contextforge/Dockerfile`) starts from the upstream image of the same
version (`ghcr.io/ibm/mcp-context-forge:<upstream version>`) and copies in the
files under `mcpgateway/` that differ between the upstream tag and our tag. It
first checks that the base image's copies match the upstream tag, so a mismatch
stops the build. Only Python changes under `mcpgateway/` can ship this way: a
patch that touches dependencies, the frontend, Rust crates or anything else
outside `mcpgateway/` needs a full image build from this repo's `Containerfile`.

## Carried patches (on v1.1.0)

| # | Commit | What | Upstream status |
|---|--------|------|-----------------|
| 1 | fix(auth): don't count request-only scopes as missing from OAuth tokens | `openid`, `offline_access`, `profile`, `email` and Entra `<resource>/.default` are not counted as missing from a token's scope claim | PR #7047 open, not reviewed (part of issue #4158) |
| 2 | fix(oauth): re-send configured scopes on token refresh | the refresh request carries the configured scopes (Entra AADSTS90009) | PR #7048 open, not reviewed |
| 3 | fix(rpc): report tools/call failures as isError results on /rpc | plugin denials and `ToolInvocationError` on `/rpc` tools/call return an `isError` result the model can read | issue #7055, PR #7056 open, not reviewed. On v1.1.0 one trivial conflict in `main.py` (upstream's new `_object_only_structured_content` line next to our `except`; both kept) |
| 4 | feat(oauth): let a person list and revoke their own per-user OAuth connections | `GET /oauth/connections`, `DELETE /oauth/connections/{gateway_id}` | no PR. Related: #5501, #5594. v1.0.11 adds status only, still missing in v1.1.0 |
| 5 | fix(identity): propagate the identity of OAuth access-token callers to upstreams | the OAuth transport branch records the identity, `invoke_tool` falls back to `user_identity_var`, affinity-forwarded calls keep it | not reported yet |

Two test-only commits follow the five patches on v1.1.0: 1.1.0 refreshes tokens
through `get_isolated_http_client` and calls upstreams through
`mcp_proxy_client` (MCP SDK 2), so the mocks in the tests of patches 2 and 5
moved. They change no behavior.

Patches 1 to 3 are cherry-picked from the owner's upstream PR branches
(`adgregory/mcp-context-forge`: `fix/entra-request-only-scopes`,
`fix/oauth-refresh-send-scope`, `fix/rpc-tools-call-iserror`), so the fork and
the PRs stay the same code.

## Rebasing onto a new upstream release

```sh
git fetch upstream --tags
git checkout -b kairos/vX.Y.Z vX.Y.Z
git cherry-pick <patch commits from the previous kairos/ branch, in order>
```

For each patch:

1. If the release already contains it (check the PR state and the code), drop
   it and update the table above.
2. If it conflicts, resolve it against the new code and rerun its tests.
3. Watch for clean cherry-picks that still break: patch 3 applied cleanly on
   v1.0.10 but needed an import. Always run the tests.

Then:

```sh
uv sync --frozen
uv run pytest -n 8 tests/unit          # or at least the files each patch touches
git tag vX.Y.Z-kairos.1
git push origin kairos/vX.Y.Z vX.Y.Z-kairos.1
gh repo edit kairos-ai-global/mcp-context-forge --default-branch kairos/vX.Y.Z
```

In the connector, bump the base image, `CF_UPSTREAM_TAG`, `CF_TAG` and
`CF_COMMIT` in `images/contextforge/Dockerfile`, and rebuild. The build fails if
the base image does not match the upstream tag or if the fork changes anything
outside `mcpgateway/`, `tests/` and this file.

A fix within the same upstream version is a new commit on the branch and the
next `-kairos.<n>` tag. Never move a published tag: the connector pins its
commit.
