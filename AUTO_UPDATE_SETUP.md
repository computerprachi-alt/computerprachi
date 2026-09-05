# Computer Prachi Auto Update

This website includes a GitHub Actions updater. It checks `https://sarkariresult.com.cm/` every 30 minutes and updates the job, result, admit card, answer key, admission, 10th/ITI, outsourcing and syllabus listings.

## Enable it
1. Upload/replace these files in the same GitHub repository that hosts Computer Prachi.
2. Make sure **Actions** are enabled for the repository.
3. Open **Actions → Computer Prachi Auto Update → Run workflow** once for the first manual update.
4. After that, the scheduled workflow runs every 30 minutes and commits changes automatically.

The workflow uses the repository's built-in `GITHUB_TOKEN`; no password or personal token is stored in the site files.
