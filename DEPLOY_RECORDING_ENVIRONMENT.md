# Recording Environment Deployment

The live site is Cloudflare Pages:

https://recording-environment.pages.dev/

## Source Folder

The public site source is:

```text
Deploy/live
```

Do not assume a Git push alone updates the production site.

## Production Deploy Command

Use the script:

```powershell
.\tools\deploy_recording_environment.ps1
```

The script deploys:

```powershell
npx wrangler pages deploy Deploy/live --project-name=recording-environment --branch=main --commit-dirty=true
```

Then it verifies the production URL contains `Tape Converter`.

## Manual Verification

```powershell
(Invoke-WebRequest https://recording-environment.pages.dev/ -UseBasicParsing).Content |
  Select-String "Tape Converter"
```

## Required Rule

For public website updates:

1. Edit files under `Deploy/live`.
2. Commit and push the site files that should be preserved in Git.
3. Run `.\tools\deploy_recording_environment.ps1`.
4. Verify `https://recording-environment.pages.dev/`.

