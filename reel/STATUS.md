# Status — B-roll pass blocked at preflight (2026-10-09)

Nothing was searched, downloaded, rendered or changed. The B-roll step stopped at preflight:

| check | result |
|---|---|
| `PEXELS_API_KEY` is set | **FAIL**: the variable isn't set in this environment |
| `api.pexels.com` search returns 200 | **FAIL**: the egress proxy refused the connection (`connect_rejected`, organization network policy), so no HTTP code came back (000) |
| `videos.pexels.com` connects | **FAIL**: `connect_rejected` by the egress proxy |
| `images.pexels.com` connects | **FAIL**: `connect_rejected` by the egress proxy |

## Unblocking it

1. Add `PEXELS_API_KEY` to the cloud environment's settings (environment menu → Edit → secrets / environment variables).
2. Network access: in the same settings, allow `api.pexels.com`, `videos.pexels.com` and `images.pexels.com` under Allowed domains, or pick a broader access level. See <https://code.claude.com/docs/en/cloud-environments#network-access>.
3. Start a new session, which picks up both changes, and re-run the B-roll task.

The existing NoMusic preview with B-roll placeholders, described in README.md, is unchanged.
