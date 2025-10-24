$Action = New-ScheduledTaskAction -Execute "C:\Python313\python.exe" -Argument '-u "F:\Python_Projects\Auto_YT_DL\auto_yt_live.py"' -WorkingDirectory "F:\Python_Projects\Auto_YT_DL"
$Trigger = New-ScheduledTaskTrigger -Daily -At 8:30AM

# --- UPDATED SETTINGS ---
# Added -WakeToRun to allow the task to wake the computer from sleep or hibernate.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 -WakeToRun

# Task name and description
$TaskName = "YouTubeLiveDownloader"
# Updated description to match the 8:30 AM trigger time
$Description = "Runs YouTube Live downloader script daily at 8:30 AM"

# Register the scheduled task (needs to be run as administrator)
# This will overwrite any existing task with the same name because of -Force
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description $Description -Force

Write-Host "Task '$TaskName' has been registered and is set to wake the computer."
