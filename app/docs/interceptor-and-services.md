# Interceptor & Services Recovery Notes

## Overview

The system runs a **Snowflake Cortex proxy** (`interceptor`) that translates Anthropic/OpenAI API requests into Snowflake Cortex API calls. It sits between clients (Claude Code CLI, OpenVSCode Claude Code extension) and the Snowflake Cortex `/api/v2/cortex/v1` endpoint.

## Architecture

```
Claude Code (CLI/VSCode) 
    → http://localhost:8766 (interceptor)
        → https://<org>-<account>.snowflakecomputing.com/api/v2/cortex/v1
```

### Key files

| File | Purpose |
|------|---------|
| `/home/azureuser/.local/bin/interceptor` | The proxy binary (built from Rust) |
| `/home/azureuser/.config/interceptor/config.toml` | Interceptor configuration |
| `/home/azureuser/afe_claw/config/supervisord.conf` | Supervisord config for all services |
| `/home/azureuser/.claude/settings.json` | Claude Code settings (env vars, model overrides) |
| `/home/azureuser/.claude/.credentials.json` | Claude Code OAuth credentials |
| `/home/azureuser/.openvscode-server/data/User/settings.json` | OpenVSCode user settings |
| `/home/azureuser/.bashrc` | Shell env vars (`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`) |

### Services managed by supervisord

All started via: `/home/azureuser/afe_claw/.pixi/envs/default/bin/supervisord -c /home/azureuser/afe_claw/config/supervisord.conf`

| Service | Port | Description |
|---------|------|-------------|
| postgres | 5432 | PostgreSQL database |
| backend | 9000 | Uvicorn (FastAPI) backend |
| frontend | 9001 | Vite dev server |
| nginx | 80/443 | Reverse proxy |
| openvscode | 9002 | OpenVSCode Server |
| interceptor | 8766 | Snowflake Cortex proxy |

### Supervisorctl commands

```bash
# Use the pixi-managed supervisorctl with the custom config
/home/azureuser/afe_claw/.pixi/envs/default/bin/supervisorctl -c /home/azureuser/afe_claw/config/supervisord.conf status
/home/azureuser/afe_claw/.pixi/envs/default/bin/supervisorctl -c /home/azureuser/afe_claw/config/supervisord.conf restart <service>
```

## Issue: Services down after reboot (2026-05-28)

### Root cause
Azure VM kernel update reboot (`5.15.0-1053` → `5.15.0-1089`). Supervisord has no systemd unit or `@reboot` crontab, so nothing starts automatically.

### Resolution
```bash
rm -f /home/azureuser/afe_claw/logs/supervisor.sock /home/azureuser/afe_claw/logs/supervisord.pid
/home/azureuser/afe_claw/.pixi/envs/default/bin/supervisord -c /home/azureuser/afe_claw/config/supervisord.conf
```

### TODO: Auto-start on boot
Supervisord does not auto-start after reboot. Consider adding a systemd user service or `@reboot` crontab entry.

## Issue: "unknown model claude-4-opus" in OpenVSCode Claude Code extension

### Problem
The Claude Code extension sends model names like `claude-4-opus` or `claude-4-opus[1m]` which Snowflake Cortex doesn't recognize. Valid Cortex model names are: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`, etc.

### Root cause (old binary from March 2026)
The old interceptor binary had built-in model name normalization for known models (sonnet, haiku) but did NOT know about `claude-opus-4-7` (released after the binary was compiled). Unknown models went through a "passthrough" code path that forwarded the request directly to Snowflake without applying the `[model_map]` config.

Key finding: The `[model_map]` config section only works on the NON-passthrough code path. The passthrough path (triggered for unrecognized models) bypasses it entirely.

### Resolution: Rebuild interceptor from source

Source repo: `https://github.com/sfc-gh-kkeller/prompt_policy_interceptor`

```bash
# Install rust via pixi (already added to pixi.toml)
# Clone and build
git clone https://github.com/sfc-gh-kkeller/prompt_policy_interceptor /tmp/prompt_policy_interceptor
cd /tmp/prompt_policy_interceptor/cortex-proxy-rs
/home/azureuser/.pixi/bin/pixi run --manifest-path /home/azureuser/afe_claw/pixi.toml cargo build --release

# Install (stop interceptor first)
/home/azureuser/afe_claw/.pixi/envs/default/bin/supervisorctl -c /home/azureuser/afe_claw/config/supervisord.conf stop interceptor
cp /home/azureuser/.local/bin/interceptor /home/azureuser/.local/bin/interceptor.old
cp /tmp/prompt_policy_interceptor/cortex-proxy-rs/target/release/interceptor /home/azureuser/.local/bin/interceptor
chmod +x /home/azureuser/.local/bin/interceptor
/home/azureuser/afe_claw/.pixi/envs/default/bin/supervisorctl -c /home/azureuser/afe_claw/config/supervisord.conf start interceptor

# Clean up
rm -rf /tmp/prompt_policy_interceptor
```

### Interceptor config (`~/.config/interceptor/config.toml`)

```toml
[proxy]
port = 8766
log_level = "info"
timeout_secs = 300

[snowflake]
base_url = "https://<org>-<account>.snowflakecomputing.com/api/v2/cortex/v1"
pat = "<PAT token>"
default_model = "claude-sonnet-4-20250514"

[model_map]
claude-4-opus = "claude-opus-4-7"
"claude-4-opus[1m]" = "claude-opus-4-7"
claude-opus-4 = "claude-opus-4-7"
"claude-opus-4[1m]" = "claude-opus-4-7"
claude-4-sonnet = "claude-sonnet-4-6"
"claude-4-sonnet[1m]" = "claude-sonnet-4-6"
claude-sonnet-4 = "claude-sonnet-4-6"
"claude-sonnet-4[1m]" = "claude-sonnet-4-6"
claude-4-haiku = "claude-haiku-4-5"
claude-haiku-4 = "claude-haiku-4-5"
```

**Note on `[1m]` suffix:** Claude Code extension appends context window size suffixes (e.g., `[1m]`) to model names. The model_map must include entries for both bare and suffixed variants.

## Claude Code extension routing

### How it decides where to send requests

1. If `.credentials.json` exists with OAuth → uses OAuth auth
2. If `ANTHROPIC_API_KEY` is set → uses API key auth
3. `ANTHROPIC_BASE_URL` controls the endpoint (default: `https://api.anthropic.com`)

**Critical:** When OAuth credentials exist AND `ANTHROPIC_BASE_URL` is set, the extension uses OAuth auth but sends to the custom base URL. This means requests go to the interceptor with an OAuth bearer token (which the interceptor ignores, using its own PAT for Snowflake).

### Environment variable setup

Set in three places for belt-and-suspenders:

1. **~/.bashrc** (for terminal/CLI sessions):
   ```bash
   export ANTHROPIC_BASE_URL=http://localhost:8766
   export ANTHROPIC_API_KEY=dummy-key-proxy-handles-auth
   ```

2. **~/.claude/settings.json** (native Claude Code config, read by the binary directly):
   ```json
   {
     "env": {
       "ANTHROPIC_BASE_URL": "http://localhost:8766",
       "ANTHROPIC_API_KEY": "dummy-key-proxy-handles-auth"
     }
   }
   ```

3. **supervisord.conf openvscode section** (for the VSCode server process):
   ```ini
   environment=ANTHROPIC_BASE_URL="http://localhost:8766",ANTHROPIC_API_KEY="dummy-key-proxy-handles-auth"
   ```

## Debugging tips

### Test interceptor directly
```bash
curl -s http://localhost:8766/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: test" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-4-opus","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'
```

### Enable debug logging
Change `log_level = "info"` to `log_level = "debug"` in config.toml and restart. Debug output goes to interceptor_stderr.log.

### Check if extension is hitting interceptor
```bash
tail -f /home/azureuser/afe_claw/logs/interceptor_stdout.log
```

### Check Claude Code process env
```bash
pgrep -a "native-binary/claude"
cat /proc/<PID>/environ | tr '\0' '\n' | grep ANTHROPIC
```

### Valid Snowflake Cortex model names (as of May 2026)
- `claude-opus-4-7` (1M context, 128K output)
- `claude-opus-4-6` (1M context, 128K output)
- `claude-sonnet-4-6` (1M context, 64K output)
- `claude-sonnet-4-5` (200K context, 64K output)
- `claude-haiku-4-5` (200K context, 64K output)

### Disk space
The build needs ~2GB. If disk is full:
```bash
# Remove old cortex versions (keep latest)
ls -t /home/azureuser/.local/share/cortex/ | tail -n +2 | xargs -I{} rm -rf /home/azureuser/.local/share/cortex/{}
# Clean caches
rm -rf /home/azureuser/.cache/rattler /home/azureuser/.cache/pixi
```
