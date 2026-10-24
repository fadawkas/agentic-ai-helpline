# Browser Verification Setup

Frontend skills require viewing the rendered result when browser tools are
available. Configure Playwright MCP globally so that workflow is available in
every project.

Add the following to `~/.config/opencode/opencode.json`, preserving existing
fields and the `$schema` entry:

```json
{
  "mcp": {
    "playwright": {
      "type": "local",
      "command": ["npx", "-y", "@playwright/mcp@latest"],
      "enabled": true
    }
  }
}
```

Use Playwright to open the local application, operate the changed flow, capture
screenshots, and inspect console errors. For visual screenshot inspection, add
the `--caps=vision` argument if the installed server requires it. Keep browser
automation scoped to the local application unless the task requires another
site.

After changing OpenCode configuration, quit and restart OpenCode; configuration,
skills, and agents are loaded at startup.
