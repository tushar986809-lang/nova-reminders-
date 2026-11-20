# nova-reminders-
NOVA reminder backend: GitHub Actions checks encrypted reminders and sends alerts.

# NOVA Reminders

Backend for NOVA, my personal AI assistant project.
A GitHub Actions job runs every few minutes, checks encrypted reminders in reminders.json
and sends an alert (phone call) when one is due, even if my laptop is off.

Built with Python, GitHub Actions and the Twilio API.
Reminder text is encrypted (Fernet), and all keys are stored in GitHub Secrets.
